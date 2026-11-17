-- Run as postgres against cnpg-immich/app after tools/immich-db-owner.sql.
-- Checks are transactional and leave no test objects or data behind.
\set ON_ERROR_STOP on
BEGIN;
DO $check$
BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'app'
             AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)) THEN
    RAISE EXCEPTION 'Immich app role has elevated cluster privileges';
  END IF;
  IF EXISTS (SELECT FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S')
               AND c.relowner <> 'app'::regrole
               AND NOT EXISTS (SELECT FROM pg_depend d WHERE d.classid = 'pg_class'::regclass
                               AND d.objid = c.oid AND d.deptype = 'e')) THEN
    RAISE EXCEPTION 'Immich application relation is not owned by app';
  END IF;
END
$check$;
SET LOCAL ROLE app;
CREATE TABLE public.immich_owner_qa (id integer PRIMARY KEY, value text);
INSERT INTO public.immich_owner_qa VALUES (1, 'qa');
UPDATE public.immich_owner_qa SET value = 'checked' WHERE id = 1;
DELETE FROM public.immich_owner_qa WHERE id = 1;
ALTER TABLE public.immich_owner_qa ADD COLUMN checked boolean;
SELECT count(*) > 0 AS existing_assets_readable FROM public.asset;
SELECT count(*) = 7 AS required_extensions_present FROM pg_extension
WHERE extname IN ('cube', 'pg_trgm', 'unaccent', 'uuid-ossp', 'vector', 'vchord', 'earthdistance');
ROLLBACK;
