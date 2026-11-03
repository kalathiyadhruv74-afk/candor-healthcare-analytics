"""Ensure MySQL connections are never left open after a Vercel request."""

from predictor.db_utils import close_db


class CloseDbConnectionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        close_db()
        try:
            response = self.get_response(request)
            return response
        finally:
            close_db()
