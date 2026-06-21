-- v2: detalle de producto — EAN, unidades reales, empaque y categorías Jumbo.
-- Idempotente: se puede ejecutar más de una vez sin error.
-- Nombres de columna = atributo Jumbo normalizado a snake_case ASCII.

ALTER TABLE product ADD COLUMN IF NOT EXISTS ean VARCHAR(14);
ALTER TABLE product ADD COLUMN IF NOT EXISTS ean_checked_at TIMESTAMPTZ;

-- Contenido real del SKU (de SkuData de Constructor.io):
--   measurement_unit_un: unidad base normalizada (kg, l, ml, g, un)
--   unit_multiplier_un:  contenido total en esa unidad (ej: 0.47 l, 7.92 l, 0.25 kg)
ALTER TABLE product ADD COLUMN IF NOT EXISTS measurement_unit_un VARCHAR(5);
ALTER TABLE product ADD COLUMN IF NOT EXISTS unit_multiplier_un DOUBLE PRECISION;

-- Columnas que NO se persisten (se eliminan si una migración previa las creó):
--   tipo_de_producto / category_path: el tipo va por product_type_id (FK a producttype).
--   id_grupo / id_subrubro: taxonomía interna de Jumbo, sin uso en la app.
--   envase / origen / pais_de_origen: facetas Jumbo, sin uso en la app.
ALTER TABLE product DROP COLUMN IF EXISTS tipo_de_producto;
ALTER TABLE product DROP COLUMN IF EXISTS category_path;
ALTER TABLE product DROP COLUMN IF EXISTS id_grupo;
ALTER TABLE product DROP COLUMN IF EXISTS id_subrubro;
ALTER TABLE product DROP COLUMN IF EXISTS envase;
ALTER TABLE product DROP COLUMN IF EXISTS origen;
ALTER TABLE product DROP COLUMN IF EXISTS pais_de_origen;

-- ref_id de Jumbo: termina en '-PAK' cuando el SKU es un pack
ALTER TABLE product ADD COLUMN IF NOT EXISTS ref_id VARCHAR(50);
ALTER TABLE product ADD COLUMN IF NOT EXISTS cart_limit INTEGER;

-- Búsqueda por código de barras desde la app
CREATE INDEX IF NOT EXISTS ix_product_ean ON product (ean) WHERE ean IS NOT NULL;

-- Scan eficiente del backfill (productos pendientes de EAN)
CREATE INDEX IF NOT EXISTS ix_product_ean_pending
    ON product (sku) WHERE ean IS NULL AND ean_checked_at IS NULL;
