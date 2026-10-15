from datetime import UTC, datetime, timedelta

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobServiceClient, ContainerSasPermissions, generate_container_sas

account = "etlstore"
key = "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
service = BlobServiceClient(account_url=f"http://127.0.0.1:10000/{account}", credential=key)
for name in ("raw", "curated"):
    try:
        service.create_container(name)
    except ResourceExistsError:
        pass

sample = """order_id,customer_id,amount,currency,status
1001,c-9,12.50,USD,paid
1002,c-4,8.00,USD,cancelled
1003,c-9,3.25,USD,paid
"""
service.get_blob_client("raw", "orders/2026-10-06.csv").upload_blob(sample, overwrite=True)


def sas(container: str, *, read: bool, create: bool, write: bool) -> str:
    return generate_container_sas(
        account,
        container,
        account_key=key,
        permission=ContainerSasPermissions(read=read, create=create, write=write),
        start=datetime.now(UTC) - timedelta(minutes=5),
        expiry=datetime.now(UTC) + timedelta(hours=4),
        protocol="https,http",
    )


print("RAW_READ_SAS=" + sas("raw", read=True, create=False, write=False))
print("CURATED_WRITE_SAS=" + sas("curated", read=False, create=True, write=True))
print("BLOB_ENDPOINT=http://host.docker.internal:10000/etlstore")
