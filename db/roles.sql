-- Two roles: app_admin (owner/writer), app_readonly (SELECT-only for the agent)

-- app_admin already exists (POSTGRES_USER). Grant it schema ownership.
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO app_admin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_admin;

-- Create read-only role if it does not already exist.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = 'app_readonly'
    ) THEN
        CREATE ROLE app_readonly
            LOGIN
            PASSWORD 'readonly_pass_change_me';
    END IF;
END
$$;

-- Agent may only read the 4 business tables. Not agent_runs.
GRANT CONNECT ON DATABASE ai_data_agent TO app_readonly;
GRANT USAGE ON SCHEMA public TO app_readonly;
GRANT SELECT ON customers, products, orders, order_items TO app_readonly;

-- Belt-and-braces: force read-only at the session level.
ALTER ROLE app_readonly SET default_transaction_read_only = on;
ALTER ROLE app_readonly SET statement_timeout = '5s';