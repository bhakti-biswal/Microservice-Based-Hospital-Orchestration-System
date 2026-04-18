import grpc
import uuid
from concurrent import futures
from datetime import datetime

import billing_service_pb2
import billing_service_pb2_grpc

# ── In-Memory Store ───────────────────────────────────────────────────────────
billing_accounts: dict[str, dict] = {}


# ── gRPC Servicer ─────────────────────────────────────────────────────────────
class BillingServiceServicer(billing_service_pb2_grpc.BillingServiceServicer):

    def CreateBillingAccount(self, request, context):
        if request.patient_id in billing_accounts:
            # Idempotent: return existing account
            acc = billing_accounts[request.patient_id]
            return billing_service_pb2.BillingResponse(
                account_id=acc["account_id"],
                patient_id=acc["patient_id"],
                patient_name=acc["patient_name"],
                status=acc["status"],
                message="Billing account already exists",
            )

        account_id = str(uuid.uuid4())
        billing_accounts[request.patient_id] = {
            "account_id": account_id,
            "patient_id": request.patient_id,
            "patient_name": request.patient_name,
            "email": request.email,
            "address": request.address,
            "status": "ACTIVE",
            "created_at": datetime.utcnow().isoformat(),
        }
        print(f"✅ [Billing] Created account {account_id} for patient {request.patient_id}")
        return billing_service_pb2.BillingResponse(
            account_id=account_id,
            patient_id=request.patient_id,
            patient_name=request.patient_name,
            status="ACTIVE",
            message="Billing account created successfully",
        )

    def GetBillingAccount(self, request, context):
        acc = billing_accounts.get(request.patient_id)
        if not acc:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Billing account for patient {request.patient_id} not found")
            return billing_service_pb2.BillingResponse()
        return billing_service_pb2.BillingResponse(
            account_id=acc["account_id"],
            patient_id=acc["patient_id"],
            patient_name=acc["patient_name"],
            status=acc["status"],
            message="Billing account retrieved successfully",
        )

    def UpdateBillingAccount(self, request, context):
        acc = billing_accounts.get(request.patient_id)
        if not acc:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Billing account for patient {request.patient_id} not found")
            return billing_service_pb2.BillingResponse()
        acc.update({
            "patient_name": request.patient_name or acc["patient_name"],
            "email": request.email or acc["email"],
            "address": request.address or acc["address"],
            "updated_at": datetime.utcnow().isoformat(),
        })
        billing_accounts[request.patient_id] = acc
        print(f"✏️  [Billing] Updated account for patient {request.patient_id}")
        return billing_service_pb2.BillingResponse(
            account_id=acc["account_id"],
            patient_id=acc["patient_id"],
            patient_name=acc["patient_name"],
            status=acc["status"],
            message="Billing account updated successfully",
        )


# ── Server Startup ────────────────────────────────────────────────────────────
def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    billing_service_pb2_grpc.add_BillingServiceServicer_to_server(BillingServiceServicer(), server)
    listen_addr = "[::]:50051"
    server.add_insecure_port(listen_addr)
    server.start()
    print(f"🚀 Billing gRPC server started on {listen_addr}")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
