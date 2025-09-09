CREATE EXTENSION IF NOT EXISTS vector;

DROP VIEW IF EXISTS app_inventory CASCADE;

DO $$
DECLARE
  has_store_col  boolean := EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='vip_items' AND column_name='store'
  );
  has_source_id  boolean := EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='vip_items' AND column_name='vip_source_id'
  );
BEGIN
  IF has_store_col THEN
    EXECUTE $f$
      CREATE OR REPLACE VIEW app_inventory AS
      SELECT
        i.*,
        COALESCE(NULLIF(TRIM(p.consumer_product_name), ''),
                 NULLIF(TRIM(p.product_name), ''),
                 NULLIF(TRIM(p.product_short_name), ''),
                 NULLIF(TRIM(p.fanciful_name), ''),
                 'Unknown')::text AS product_name,
        COALESCE(NULLIF(TRIM(b.consumer_brand_name), ''),
                 NULLIF(TRIM(b.brand_name), ''),
                 NULLIF(TRIM(b.brand_short_name), ''),
                 'Unknown')::text AS brand_name
      FROM vip_items i
      JOIN vip_products p ON p.vip_product_id = i.vip_product_id
      JOIN vip_brands   b ON b.vip_brand_id   = p.vip_brand_id;
    $f$;
  ELSIF has_source_id THEN
    EXECUTE $f$
      CREATE OR REPLACE VIEW app_inventory AS
      SELECT
        i.*, 
        ('source_' || i.vip_source_id::text) AS store,
        COALESCE(NULLIF(TRIM(p.consumer_product_name), ''),
                 NULLIF(TRIM(p.product_name), ''),
                 NULLIF(TRIM(p.product_short_name), ''),
                 NULLIF(TRIM(p.fanciful_name), ''),
                 'Unknown')::text AS product_name,
        COALESCE(NULLIF(TRIM(b.consumer_brand_name), ''),
                 NULLIF(TRIM(b.brand_name), ''),
                 NULLIF(TRIM(b.brand_short_name), ''),
                 'Unknown')::text AS brand_name
      FROM vip_items i
      JOIN vip_products p ON p.vip_product_id = i.vip_product_id
      JOIN vip_brands   b ON b.vip_brand_id   = p.vip_brand_id;
    $f$;
  ELSE
    EXECUTE $f$
      CREATE OR REPLACE VIEW app_inventory AS
      SELECT
        i.*,
        NULL::text AS store,
        COALESCE(NULLIF(TRIM(p.consumer_product_name), ''),
                 NULLIF(TRIM(p.product_name), ''),
                 NULLIF(TRIM(p.product_short_name), ''),
                 NULLIF(TRIM(p.fanciful_name), ''),
                 'Unknown')::text AS product_name,
        COALESCE(NULLIF(TRIM(b.consumer_brand_name), ''),
                 NULLIF(TRIM(b.brand_name), ''),
                 NULLIF(TRIM(b.brand_short_name), ''),
                 'Unknown')::text AS brand_name
      FROM vip_items i
      JOIN vip_products p ON p.vip_product_id = i.vip_product_id
      JOIN vip_brands   b ON b.vip_brand_id   = p.vip_brand_id;
    $f$;
  END IF;
END $$;
