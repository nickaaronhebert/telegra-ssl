-- Migration: Add DNS check fields to clients table
-- Date: 2025-01-13
-- Description: Add fields to store DNS check results for client domains

ALTER TABLE clients ADD COLUMN IF NOT EXISTS dns_check_status VARCHAR;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS dns_check_resolved_to VARCHAR;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS dns_check_resolved_ips TEXT;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS dns_check_error TEXT;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS dns_check_last_checked TIMESTAMP;

-- Add comments for documentation
COMMENT ON COLUMN clients.dns_check_status IS 'DNS check status: correct, incorrect, missing, error, not_checked';
COMMENT ON COLUMN clients.dns_check_resolved_to IS 'CNAME target if DNS uses CNAME record';
COMMENT ON COLUMN clients.dns_check_resolved_ips IS 'JSON array of resolved IP addresses if DNS uses A records';
COMMENT ON COLUMN clients.dns_check_error IS 'Error message if DNS check failed';
COMMENT ON COLUMN clients.dns_check_last_checked IS 'Timestamp of last DNS check';
