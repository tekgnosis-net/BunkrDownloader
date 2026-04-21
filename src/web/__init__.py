"""Web service package for the FastAPI interface.

The FastAPI ``app`` object is deliberately NOT re-exported here — importing
it at package level shadows the ``src.web.app`` submodule and breaks
``unittest.mock.patch("src.web.app.<name>", ...)`` via its attribute-traversal
resolver. Import the app directly with ``from src.web.app import app``
(or ``uvicorn src.web.app:app`` for the command line).
"""
