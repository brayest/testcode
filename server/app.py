import os
import flask
import cloudinary
import sys
from loguru import logger
from pathlib import Path

from server.consts import DEBUG_MODE, LOG_RETENTION
from server.app_config import Config
from server.api.blueprints import login, user, teacher, student, appointments, topics
from server.extensions import login_manager
from server.api.database import database
from server import error_handling
from server.api import push_notifications, babel


def register_extensions_and_blueprints(flask_app):
    """Register Flask extensions and blueprints (each has init_app method)."""
    for module in (
        database,
        login_manager,
        error_handling,
        login,
        appointments,
        topics,
        user,
        teacher,
        student,
        push_notifications,
        babel,
    ):
        module.init_app(flask_app)


def create_app(**test_config):
    """An application factory, as explained here: http://flask.pocoo.org/docs/patterns/appfactories/.
    :param config: The configuration object to use.
    """
    flask_app = flask.Flask(__name__)
    path_to_logs = Path(__file__).resolve().parents[1]
    log_file = str(path_to_logs / "logs" / "dryvo_log.log")
    logger.add(log_file, retention=LOG_RETENTION)
    logger.debug("Starting Flask app")
    config = Config()
    config.update(test_config)
    flask_app.config.from_object(config)
    register_extensions_and_blueprints(flask_app)
    add_endpoints(flask_app)
    return flask_app


# app = create_app(Config)


def add_endpoints(app):
    @app.route("/")
    def home():
        return "Debug mode enabled!" if DEBUG_MODE else "Production mode enabled!"
