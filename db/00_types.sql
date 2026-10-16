-- Runs BEFORE the tables are created from app/models.py.
-- The models declare these two enum types with create_type=False (their DDL
-- came from migration 048), so create_all needs them to exist first. The
-- other enum types are created by create_all itself.

CREATE SCHEMA IF NOT EXISTS item_schema;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_permission_state') THEN
        CREATE TYPE public.user_permission_state AS ENUM ('inherit', 'grant', 'block');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'department_permission_state') THEN
        CREATE TYPE public.department_permission_state AS ENUM ('grant', 'block');
    END IF;
END
$$;
