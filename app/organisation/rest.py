from flask import Blueprint, jsonify, request, current_app
from sqlalchemy.exc import IntegrityError

from app.dao.organisation_dao import (
    dao_create_organisation,
    dao_get_organisations,
    dao_get_organisation_by_id,
    dao_get_organisation_services,
    dao_update_organisation,
    dao_add_service_to_organisation,
    dao_get_users_for_organisation,
    dao_add_user_to_organisation
)
from app.dao.services_dao import dao_fetch_service_by_id
from app.errors import register_errors, InvalidRequest
from app.models import Organisation
from app.organisation.organisation_schema import (
    post_create_organisation_schema,
    post_update_organisation_schema,
    post_link_service_to_organisation_schema,
)
from app.schema_validation import validate
from app.schemas import user_schema

organisation_blueprint = Blueprint('organisation', __name__)
register_errors(organisation_blueprint)


@organisation_blueprint.errorhandler(IntegrityError)
def handle_integrity_error(exc):
    """
    Handle integrity errors caused by the unique constraint on ix_organisation_name
    """
    if 'ix_organisation_name' in str(exc):
        return jsonify(result="error",
                       message="Organisation name already exists"), 400

    current_app.logger.exception(exc)
    return jsonify(result='error', message="Internal server error"), 500


@organisation_blueprint.route('', methods=['GET'])
def get_organisations():
    organisations = [
        org.serialize() for org in dao_get_organisations()
    ]

    return jsonify(organisations)


@organisation_blueprint.route('/<uuid:organisation_id>', methods=['GET'])
def get_organisation_by_id(organisation_id):
    organisation = dao_get_organisation_by_id(organisation_id)
    return jsonify(organisation.serialize())


@organisation_blueprint.route('', methods=['POST'])
def create_organisation():
    data = request.get_json()

    validate(data, post_create_organisation_schema)

    organisation = Organisation(**data)
    dao_create_organisation(organisation)
    return jsonify(organisation.serialize()), 201


@organisation_blueprint.route('/<uuid:organisation_id>', methods=['POST'])
def update_organisation(organisation_id):
    data = request.get_json()
    validate(data, post_update_organisation_schema)
    result = dao_update_organisation(organisation_id, **data)
    if result:
        return '', 204
    else:
        raise InvalidRequest("Organisation not found", 404)


@organisation_blueprint.route('/<uuid:organisation_id>/service', methods=['POST'])
def link_service_to_organisation(organisation_id):
    data = request.get_json()
    validate(data, post_link_service_to_organisation_schema)
    service = dao_fetch_service_by_id(data['service_id'])
    service.organisation = None

    dao_add_service_to_organisation(service, organisation_id)

    return '', 204


@organisation_blueprint.route('/<uuid:organisation_id>/services', methods=['GET'])
def get_organisation_services(organisation_id):
    services = dao_get_organisation_services(organisation_id)
    sorted_services = sorted(services, key=lambda s: (-s.active, s.name))
    return jsonify([s.serialize_for_org_dashboard() for s in sorted_services])


@organisation_blueprint.route('/<uuid:organisation_id>/users/<uuid:user_id>', methods=['POST'])
def add_user_to_organisation(organisation_id, user_id):
    new_org_user = dao_add_user_to_organisation(organisation_id, user_id)
    return jsonify(data=user_schema.dump(new_org_user).data), 200


@organisation_blueprint.route('/<uuid:organisation_id>/users', methods=['GET'])
def get_organisation_users(organisation_id):
    org_users = dao_get_users_for_organisation(organisation_id)

    result = user_schema.dump(org_users, many=True)
    return jsonify(data=result.data)