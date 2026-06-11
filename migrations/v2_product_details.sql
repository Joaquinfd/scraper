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

-- Facetas Jumbo
ALTER TABLE product ADD COLUMN IF NOT EXISTS envase VARCHAR(50);
ALTER TABLE product ADD COLUMN IF NOT EXISTS tipo_de_producto VARCHAR(100);
ALTER TABLE product ADD COLUMN IF NOT EXISTS origen VARCHAR(30);
ALTER TABLE product ADD COLUMN IF NOT EXISTS pais_de_origen VARCHAR(60);
ALTER TABLE product ADD COLUMN IF NOT EXISTS id_grupo VARCHAR(20);
ALTER TABLE product ADD COLUMN IF NOT EXISTS id_subrubro VARCHAR(20);
ALTER TABLE product ADD COLUMN IF NOT EXISTS category_path VARCHAR(255);

-- ref_id de Jumbo: termina en '-PAK' cuando el SKU es un pack
ALTER TABLE product ADD COLUMN IF NOT EXISTS ref_id VARCHAR(50);
ALTER TABLE product ADD COLUMN IF NOT EXISTS cart_limit INTEGER;

-- Búsqueda por código de barras desde la app
CREATE INDEX IF NOT EXISTS ix_product_ean ON product (ean) WHERE ean IS NOT NULL;

-- Scan eficiente del backfill (productos pendientes de EAN)
CREATE INDEX IF NOT EXISTS ix_product_ean_pending
    ON product (sku) WHERE ean IS NULL AND ean_checked_at IS NULL;
