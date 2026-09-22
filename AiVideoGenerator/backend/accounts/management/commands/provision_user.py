from getpass import getpass

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from accounts.models import User


class Command(BaseCommand):
    help = "Create a predefined account; the password is requested securely."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", default="")
        parser.add_argument("--admin", action="store_true")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError("Enter a valid email address.") from exc
        if User.objects.filter(email=email).exists():
            raise CommandError(
                "Account already exists. Use changepassword to change its password."
            )
        password = getpass("Password: ")
        if password != getpass("Confirm password: "):
            raise CommandError("Passwords do not match.")
        try:
            validate_password(password, User(email=email, first_name=options["name"]))
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        create = User.objects.create_superuser if options["admin"] else User.objects.create_user
        create(email=email, password=password, first_name=options["name"])
        self.stdout.write(self.style.SUCCESS(f"Account created: {email}"))
