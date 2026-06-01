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

| Flag | Default | Descripción |
| --- | --- | --- |
| `--db` | off | Escribe en PostgreSQL |
| `--no-csv` | off | No genera CSV |
| `--no-jsonl` | off | No genera JSONL |
| `--out DIR` | `output` | Directorio de salida para archivos |
| `--workers N` | 1 | Categorías en paralelo |
| `--delay-min F` | 0.4 | Pausa mínima entre requests (s) |
| `--delay-max F` | 0.9 | Pausa máxima entre requests (s) |
| `--store-name` | `Jumbo Online` | Nombre de la tienda en DB |
| `--store-location` | `null` | Ubicación de la tienda en DB |
| `--verbose / -v` | off | Logging detallado |

## Qué escribe en la base de datos

Por cada producto encontrado (en orden):

1. **`producttype`** — upsert por nombre (último segmento del `categoryPath`)
2. **`product`** — upsert por `skuId`; no sobreescribe si ya existe
3. **`store`** — upsert por nombre de tienda
4. **`pricesnapshot`** — inserta siempre con timestamp UTC

> Los productos ya existentes en la DB no se sobreescriben. Ejecutar el scraper varias veces solo agrega nuevos `pricesnapshots`.

## Archivos de salida

Tras cada ejecución con `--db` se generan en `output/`:

| Archivo | Contenido |
| --- | --- |
| `categories.csv` | Todas las categorías encontradas con su unidad de medida — útil para filtrar categorías de alimentos |
| `failed_rows.csv` | Filas que no pudieron escribirse en DB y el motivo del error |
| `jumbo_productos.csv` | Catálogo completo (si `--no-csv` no está activo) |
| `jumbo_productos.jsonl` | Ídem en formato JSONL para pandas |

## Ejecución automática

El scraper se ejecuta diariamente a las **8:00 AM hora Santiago** vía GitHub Actions (`.github/workflows/scraper.yml`). Requiere el secret `DATABASE_URL` configurado en el repositorio.

Para ejecutar manualmente desde GitHub: **Actions → Daily scraper → Run workflow**.

## Estructura

```
scraper/
├── main.py                  # CLI entry point
├── requirements.txt
├── .env                     # variables de entorno (no commitear)
├── .github/
│   └── workflows/
│       └── scraper.yml      # GitHub Actions — ejecución diaria
└── jumbo_scraper/
    ├── config.py            # parámetros (URLs, delays, paginación, DB)
    ├── client.py            # sesión HTTP con reintentos y rate-limiting
    ├── categories.py        # árbol de categorías y aplanado a hojas
    ├── products.py          # paginación por categoría
    ├── parser.py            # JSON Constructor.io → filas planas (una por SKU)
    ├── storage.py           # escritura incremental a CSV / JSONL
    ├── models.py            # SQLModel table classes (espejo del schema del backend)
    ├── db.py                # DbStorage — escribe en PostgreSQL con batch commits
    └── scraper.py           # orquestador + deduplicación
```

## Buenas prácticas

- El scraper incluye pausas con jitter, reintentos con backoff exponencial y respeta códigos 429/5xx.
- Cada lote de 500 filas se confirma en un solo `COMMIT` para minimizar round trips a la DB.
- Fallos individuales usan savepoints para no afectar el lote en curso.
- Este código es para uso en proyecto universitario de formación académica.
