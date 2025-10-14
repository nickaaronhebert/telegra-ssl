import sys
sys.path.insert(0, '/home/ubuntu/client-onboarding-service/backend')
import boto3

acm = boto3.client('acm', region_name='us-east-2')

cert_arn = "arn:aws:acm:us-east-2:901120114376:certificate/ffaa2a20-6084-4fef-86d4-ee030a5cb544"
desc = acm.describe_certificate(CertificateArn=cert_arn)

print("Certificate Status:", desc["Certificate"].get("Status"))
domain_validation_options = desc["Certificate"].get("DomainValidationOptions", [])
if domain_validation_options:
    resource_record = domain_validation_options[0].get("ResourceRecord")
    if resource_record:
        print(f"DNS Name: {resource_record.get('Name')}")
        print(f"DNS Value: {resource_record.get('Value')}")
    else:
        print("ResourceRecord: Not available yet")
