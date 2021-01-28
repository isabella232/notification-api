from abc import abstractmethod
from flask_sqlalchemy import SQLAlchemy, get_state
from sqlalchemy import orm
from functools import partial
from flask import current_app


class RoutingSession(orm.Session):

    _name = None

    def __init__(self, db, autocommit=False, autoflush=False, **options):
        self.app = db.get_app()
        self.db = db
        self._model_changes = {}
        orm.Session.__init__(
            self, autocommit=autocommit, autoflush=autoflush,
            bind=db.engine,
            binds=db.get_binds(self.app), **options)

    def get_bind(self, mapper=None, clause=None):
        try:
            state = get_state(self.app)
        except (AssertionError, AttributeError, TypeError) as err:
            current_app.logger.error(
                "cant get configuration. default bind. Error:" + err)
            return orm.Session.get_bind(self, mapper, clause)

        """
        If there are no binds configured, connect using the default
        SQLALCHEMY_DATABASE_URI
        """
        if state is None or not self.app.config['SQLALCHEMY_BINDS']:
            if not self.app.debug:
                current_app.logger.debug("Connecting -> DEFAULT")
            return orm.Session.get_bind(self, mapper, clause)

        return self.load_balance(state, mapper, clause)

    @abstractmethod
    def load_balance(self, state, mapper=None, clause=None):
        pass

    @abstractmethod
    def using_bind(self, name):
        pass


class ImplicitRoutingSession(RoutingSession):

    DATA_MODIFICATION_LITERALS = [
        'update',
        'delete',
        'create',
        'copy',
        'insert',
        'drop',
        'alter'
    ]

    def __init__(self, db, autocommit=False, autoflush=False, **options):
        RoutingSession.__init__(
            self, db, autocommit=autocommit, autoflush=autoflush, **options)

    def load_balance(self, state, mapper=None, clause=None):
        # Use the explicit bind if present
        if self._name:
            self.app.logger.debug("Connecting -> {}".format(self._name))
            return state.db.get_engine(self.app, bind=self._name)

        # Writes go to the writer instance
        elif self._flushing:
            current_app.logger.debug("Connecting -> WRITER")
            return state.db.get_engine(self.app, bind='writer')

        # We might deal with an undetected writes so let's check the clause itself
        elif clause is not None and self._is_query_modify(clause.compile()):
            current_app.logger.debug("Connecting -> WRITER")
            return state.db.get_engine(self.app, bind='writer')

        # Everything else goes to the reader instance(s)
        else:
            current_app.logger.debug("Connecting -> READER")
            return state.db.get_engine(self.app, bind='reader')

    def _is_query_modify(self, query) -> bool:
        query_literals = [literal.lower() for literal in str(query).split(' ')]
        intersection = [
            literal for literal in query_literals
            if literal in self.DATA_MODIFICATION_LITERALS
        ]
        return len(intersection) > 0

    def using_bind(self, name):
        s = ImplicitRoutingSession(self.db)
        vars(s).update(vars(self))
        s._name = name
        return s


class ExplicitRoutingSession(RoutingSession):

    def __init__(self, db, autocommit=False, autoflush=False, **options):
        RoutingSession.__init__(
            self, db, autocommit=autocommit, autoflush=autoflush, **options)

    def load_balance(self, state, mapper=None, clause=None):
        # Use the explicit name if present
        if self._name:
            self.app.logger.debug("Connecting -> {}".format(self._name))
            return state.db.get_engine(self.app, bind=self._name)

        # Everything else goes to the writer instance(s)
        else:
            current_app.logger.debug("Connecting -> WRITER")
            return state.db.get_engine(self.app, bind='writer')

    def using_bind(self, name):
        s = ExplicitRoutingSession(self.db)
        vars(s).update(vars(self))
        s._name = name
        return s


class RoutingSQLAlchemy(SQLAlchemy):
    """We need to subclass SQLAlchemy in order to override create_engine options"""

    def __init__(self, *args, **kwargs):
        SQLAlchemy.__init__(self, *args, **kwargs)
        self.session.using_bind = lambda s: self.session().using_bind(s)

    def apply_driver_hacks(self, app, info, options):
        super().apply_driver_hacks(app, info, options)
        if 'connect_args' not in options:
            options['connect_args'] = {}
        options['connect_args']["options"] = "-c statement_timeout={}".format(
            int(app.config['SQLALCHEMY_STATEMENT_TIMEOUT']) * 1000
        )

    def create_scoped_session(self, options=None):
        if options is None:
            options = {}
        scopefunc = options.pop('scopefunc', None)
        return orm.scoped_session(
            partial(ImplicitRoutingSession, self, **options), scopefunc=scopefunc
        )
