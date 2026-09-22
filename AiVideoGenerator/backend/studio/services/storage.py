import os
import shutil
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class LocalStorage:
    def path(self, key):
        root = Path(settings.PRIVATE_STORAGE_ROOT).resolve()
        path = (root / key).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError("Invalid object key.")
        return path

    def put(self, key, stream, content_type):
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("wb") as destination:
                shutil.copyfileobj(stream, destination)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def open(self, key, start=0, end=None):
        stream = self.path(key).open("rb")
        stream.seek(start)
        return stream

    def size(self, key):
        return self.path(key).stat().st_size

    def delete(self, key):
        self.path(key).unlink(missing_ok=True)


class OCIStorage:
    def __init__(self):
        import oci

        self.namespace = os.getenv("OCI_NAMESPACE", "")
        self.bucket = os.getenv("OCI_BUCKET", "")
        if not self.namespace or not self.bucket:
            raise ImproperlyConfigured("Set OCI_NAMESPACE and OCI_BUCKET for private storage.")
        mode = os.getenv("OCI_AUTH_MODE", "config")
        if mode == "instance_principal":
            signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
            self.client = oci.object_storage.ObjectStorageClient(
                {"region": os.getenv("OCI_REGION") or signer.region}, signer=signer
            )
        elif mode == "config":
            config = oci.config.from_file(
                os.path.expanduser(os.getenv("OCI_CONFIG_FILE", "~/.oci/config")),
                os.getenv("OCI_CONFIG_PROFILE", "DEFAULT"),
            )
            self.client = oci.object_storage.ObjectStorageClient(config)
        else:
            raise ImproperlyConfigured("OCI_AUTH_MODE must be config or instance_principal.")
        bucket = self.client.get_bucket(self.namespace, self.bucket).data
        if bucket.public_access_type != "NoPublicAccess":
            raise ImproperlyConfigured("The OCI bucket must have NoPublicAccess enabled.")

    def put(self, key, stream, content_type):
        self.client.put_object(
            self.namespace, self.bucket, key, stream, content_type=content_type
        )

    def open(self, key, start=0, end=None):
        options = {}
        if start or end is not None:
            options["range"] = f"bytes={start}-{end if end is not None else ''}"
        return self.client.get_object(self.namespace, self.bucket, key, **options).data.raw

    def size(self, key):
        response = self.client.head_object(self.namespace, self.bucket, key)
        return int(response.headers["content-length"])

    def delete(self, key):
        self.client.delete_object(self.namespace, self.bucket, key)


def get_storage():
    return OCIStorage() if settings.STORAGE_BACKEND == "oci" else LocalStorage()
