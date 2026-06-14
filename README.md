# Scraper de catálogo — jumbo.cl

Microservicio en Python que extrae el catálogo completo de productos de jumbo.cl y escribe los datos directamente en una base de datos PostgreSQL compartida con el backend.

## Cómo funciona

El scraper consume la **API pública de Constructor.io** que usa jumbo.cl como motor de búsqueda y catálogo. Devuelve JSON estructurado (producto, SKU, precio, stock, imágenes) sin necesidad de renderizar HTML o JavaScript.

1. Obtiene el árbol de categorías vía `GET /browse/groups`
2. Recorre cada **categoría hoja** y pagina sus productos vía `GET /browse/group_id/{id}`
3. Deduplica por `skuId` (un SKU puede aparecer en varias categorías)
4. Escribe **incrementalmente** a CSV/JSONL y/o directamente a PostgreSQL

## Requisitos

- Python 3.12+
- Acceso a la base de datos PostgreSQL del proyecto (ver variables de entorno)

## Instalación

```bash
python -m venv .venv

# Windows
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Variables de entorno

Crea un archivo `.env` en la raíz del proyecto:

```env
DATABASE_URL=postgresql+psycopg://user:password@host:5432/dbname

# Opcional: DB local para el modo --dev. Si no existe, --dev cae a DATABASE_URL.
DEV_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/ddsdb
```

Formatos aceptados:

- `postgresql+psycopg://...` (recomendado, psycopg v3)
- `postgresql://...`
- `postgres://...`

> La `DATABASE_URL` debe apuntar a la misma instancia PostgreSQL que usa el backend.

## Uso

```bash
# Solo base de datos (recomendado)
python main.py --db --no-csv --no-jsonl

# Base de datos con logging detallado
python main.py --db --no-csv --no-jsonl --verbose

# Base de datos + archivos CSV y JSONL
python main.py --db

# Solo archivos locales (sin DB)
python main.py

# Opciones avanzadas
python main.py --db --workers 3          # 3 categorías en paralelo
python main.py --db --delay-min 0.8      # más pausado
python main.py --db --store-name "Jumbo Las Condes" --store-location "Las Condes"
```

### Todas las opciones

| Flag               | Default        | Descripción                          |
| ------------------ | -------------- | ------------------------------------ |
| `--db`             | off            | Escribe en PostgreSQL                |
| `--dev`            | off            | Corrida acotada a DB local (ver abajo) |
| `--no-csv`         | off            | No genera CSV                        |
| `--no-jsonl`       | off            | No genera JSONL                      |
| `--out DIR`        | `output`       | Directorio de salida para archivos   |
| `--workers N`      | 1              | Categorías en paralelo               |
| `--delay-min F`    | 0.4            | Pausa mínima entre requests (s)      |
| `--delay-max F`    | 0.9            | Pausa máxima entre requests (s)      |
| `--store-name`     | `Jumbo Online` | Nombre de la tienda en DB            |
| `--store-location` | `null`         | Ubicación de la tienda en DB         |
| `--verbose / -v`   | off            | Logging detallado                    |

### Modo desarrollo (`--dev`)

Corrida acotada para poblar una **DB local** sin tocar producción: trae **2000
productos** de las categorías **Despensa** y **Cervezas** y los escribe en la DB.

```bash
python main.py --dev
```

- Usa `DEV_DATABASE_URL` si está definida; si no, cae a `DATABASE_URL`. Avisa si
  la URL apunta a Neon (para no escribir en producción por error).
- **Crea las tablas si faltan** (conveniencia para una DB local nueva). Si la DB
  local ya tiene el esquema v1, correr antes la migración (ver *Migraciones*).
- No genera archivos; escribe solo a la DB local.

## Backfill de EAN

El código de barras (EAN) **no** viene en la API de catálogo de Constructor.io,
así que se obtiene en un paso aparte leyendo el JSON-LD de cada página de
producto. Lee de la DB los productos sin EAN, los completa y los actualiza.

```bash
# Rellena el EAN de todos los productos pendientes (ean IS NULL)
python -m jumbo_scraper.ean_backfill

# Acotar la cantidad por corrida (útil para la carga inicial de los ~62k)
python -m jumbo_scraper.ean_backfill --limit 10000 --workers 4

# Contra la DB local (junto al scraper en modo --dev)
python -m jumbo_scraper.ean_backfill --dev
```

| Flag             | Default | Descripción                                    |
| ---------------- | ------- | ---------------------------------------------- |
| `--limit N`      | todos   | Máx. de productos a procesar en esta corrida   |
| `--workers N`    | 4       | Descargas de página en paralelo                |
| `--dev`          | off     | Usa la DB local (`DEV_DATABASE_URL`)           |
| `--verbose / -v` | off     | Logging detallado                              |

Es **reanudable**: solo procesa `ean IS NULL AND ean_checked_at IS NULL`, marca
cada intento y no reintenta los que no tienen barcode. Se puede cortar y
relanzar sin repetir trabajo.

> **Flujo dev con EAN:** `python main.py --dev` (catálogo → DB local) y luego
> `python -m jumbo_scraper.ean_backfill --dev` (completa el EAN de esos productos).

## Exploración del catálogo (`explore_product.py`)

Herramienta **de solo lectura** para inspeccionar la API (no toca la DB). Útil
para ver qué campos expone un producto o exportar muestras a CSV.

```bash
# Buscar un producto y volcar todos sus campos (guarda JSON en ./exploration/)
python explore_product.py "cerveza kunstmann"

# Todos los productos de una marca
python explore_product.py --brand "Kunstmann"

# Recolección masiva acotada -> CSV en ./exploration/
python explore_product.py --bulk --limit 2000

# Igual pero además trae el EAN (más lento: 1 request por producto)
python explore_product.py --brand "Kunstmann" --fetch-ean

# Agregar el EAN a un CSV ya generado
python explore_product.py --enrich-ean exploration/archivo.csv
```

## Migraciones de esquema

El dueño del esquema es el backend, pero el repo incluye la migración v2 y un
runner para aplicarla a una DB (p. ej. la local de `--dev`):

```bash
python migrations/run_migration.py migrations/v2_product_details.sql
```

Las instrucciones para el equipo de la API están en `docs/` (`v2-api-changes.md`
y `v2-api-drop-columns.md`).

## Qué escribe en la base de datos

Por cada producto encontrado (en orden):

1. **`producttype`** — upsert por nombre, tomado de la faceta `Tipo de Producto`
   de Jumbo (ej. "Cervezas Artesanales"); si falta, usa el último segmento del
   `categoryPath`.
2. **`product`** — upsert por `skuId`: inserta los nuevos y **actualiza** los
   existentes con los campos v2 (`measurement_unit_un`, `unit_multiplier_un`,
   `ref_id`, `cart_limit`). El `ean` lo completa el backfill aparte.
3. **`store`** — upsert por nombre de tienda
4. **`pricesnapshot`** — inserta siempre con timestamp UTC

> Cada corrida agrega un `pricesnapshot` nuevo y refresca los campos v2 de los
> productos ya existentes.

## Archivos de salida

Tras cada ejecución con `--db` se generan en `output/`:

| Archivo                 | Contenido                                                                                            |
| ----------------------- | ---------------------------------------------------------------------------------------------------- |
| `categories.csv`        | Todas las categorías encontradas con su unidad de medida — útil para filtrar categorías de alimentos |
| `failed_rows.csv`       | Filas que no pudieron escribirse en DB y el motivo del error                                         |
| `jumbo_productos.csv`   | Catálogo completo (si `--no-csv` no está activo)                                                     |
| `jumbo_productos.jsonl` | Ídem en formato JSONL para pandas                                                                    |

## Ejecución automática

El scraper se ejecuta diariamente a las **8:00 AM hora Santiago** vía GitHub Actions (`.github/workflows/scraper.yml`). Requiere el secret `DATABASE_URL` configurado en el repositorio.

Para ejecutar manualmente desde GitHub: **Actions → Daily scraper → Run workflow**.

El **backfill de EAN** corre en un workflow aparte (`.github/workflows/ean-backfill.yml`):
una tanda nocturna que cubre los productos nuevos del día, más ejecución manual
(**Actions → EAN backfill → Run workflow**) con un `limit` alto para la carga
inicial de los ~62k productos.

## Estructura

```
scraper/
├── main.py                  # CLI entry point (incl. --dev)
├── explore_product.py       # herramienta de exploración (solo lectura)
├── requirements.txt
├── .env                     # variables de entorno (no commitear)
├── .github/
│   └── workflows/
│       ├── scraper.yml      # GitHub Actions — scraper diario
│       └── ean-backfill.yml # GitHub Actions — backfill de EAN
├── migrations/
│   ├── v2_product_details.sql  # migración v2 (columnas nuevas + drops)
│   └── run_migration.py        # runner de migraciones
├── docs/                    # instrucciones para la API (cambios v2)
└── jumbo_scraper/
    ├── config.py            # parámetros (URLs, delays, paginación, DB, dev)
    ├── client.py            # sesión HTTP con reintentos y rate-limiting
    ├── categories.py        # árbol de categorías, aplanado y filtro por nombre
    ├── products.py          # paginación por categoría
    ├── parser.py            # JSON Constructor.io → filas planas (una por SKU)
    ├── storage.py           # escritura incremental a CSV / JSONL
    ├── models.py            # SQLModel table classes (espejo del schema del backend)
    ├── db.py                # DbStorage — escribe en PostgreSQL con batch commits
    ├── ean_backfill.py      # backfill de EAN (reanudable, desde la DB)
    └── scraper.py           # orquestador + deduplicación
```

## Buenas prácticas

- El scraper incluye pausas con jitter, reintentos con backoff exponencial y respeta códigos 429/5xx.
- Cada lote de 500 filas se confirma en un solo `COMMIT` para minimizar round trips a la DB.
- Fallos individuales usan savepoints para no afectar el lote en curso.
- Este código es para uso en proyecto universitario de formación académica.
