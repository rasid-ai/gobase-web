"""
Issue an API key from the shell, e.g. on the VPS:

    python manage.py create_api_key <username> "Ali's laptop"

The key goes to stdout alone, so it can be piped; everything else goes to stderr.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import ApiKey


class Command(BaseCommand):
    help = "Create an API key for a user and print it once. It is not stored."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("name", help='What the key is for, e.g. "Ali\'s laptop".')

    def handle(self, *args, username, name, **options):
        user_model = get_user_model()
        try:
            user = user_model.objects.get(username=username)
        except user_model.DoesNotExist as exc:
            raise CommandError(f"No user named {username!r}.") from exc

        key, raw = ApiKey.issue(user, name)
        self.stdout.write(raw)
        self.stderr.write(
            f"Created API key {key.prefix} for {username}. Copy it now: it is not stored."
        )
