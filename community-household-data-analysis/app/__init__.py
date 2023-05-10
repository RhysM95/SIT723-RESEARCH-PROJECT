from flask import Flask

# create a Flask app instance
app = Flask(__name__)

# import the routes module
from app import routes
