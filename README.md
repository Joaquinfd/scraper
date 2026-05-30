# Scraper de catálogo — jumbo.cl

Base de código en Python para extraer **todo el catálogo de productos** de
jumbo.cl. El sitio corre sobre **VTEX** (Cencosud), así que en lugar de renderizar
HTML/JavaScript, el scraper consume la **API pública de catálogo de VTEX**, que
devuelve JSON estructurado (producto, SKU, precio, stock, imágenes). Es más
rápido, más estable y mucho menos frágil que parsear HTML.

## Estrategia

1. **Árbol de categorías** → `GET /api/catalog_system/pub/category/tree/50`
2. Se recorre cada **categoría hoja** y se paginan sus productos vía
   `GET /api/catalog_system/pub/products/search?fq=C:/<id>/&_from=&_to=&sc=1`
   - VTEX entrega máximo **50 items por request** y tiene un **tope de offset (~2500)**
     por consulta. Por eso se baja a nivel de hoja: cada hoja suele caber bajo el tope.
   - Si una hoja igual lo supera, el scraper **subdivide por marca** automáticamente.
3. **Deduplicación** por `productId` (un producto puede estar en varias categorías).
4. Escritura **incremental** a `CSV` + `JSONL` (no acumula todo en RAM → sirve para
   catálogos de cientos de miles de SKUs).

## Instalación

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

```bash
# Scrapea todo el catálogo -> ./output/jumbo_productos.csv y .jsonl
python main.py

# Más rápido (3 categorías en paralelo). Úsalo con criterio.
python main.py --workers 3 --out data

# Más cortés / lento
python main.py --delay-min 0.8 --delay-max 1.5

# Precios/stock por región (ver más abajo)
python main.py --region "<valor_de_cookie_vtex_segment>"
```

Como librería:

```python
from jumbo_scraper import Config, JumboScraper

scraper = JumboScraper(Config(workers=2, output_dir="data"))
scraper.run()
scraper.close()
```

## Salida

Una fila **por SKU** con columnas: `productId, productName, brand, categoryPath,
skuId, ean, price, listPrice, available, availableQuantity, sellerName, imageUrl,
productUrl, scrapedAt`, entre otras.

- `jumbo_productos.csv`  — abre directo en Excel (UTF-8 BOM).
- `jumbo_productos.jsonl` — un JSON por línea, ideal para procesar con pandas:
  ```python
  import pandas as pd
  df = pd.read_json("output/jumbo_productos.jsonl", lines=True)
  ```

## Regionalización (precios y stock)

En VTEX el precio/stock puede variar por región. El parámetro `--region` setea la
cookie `vtex_segment`. Para obtener ese valor: abre jumbo.cl, elige tu comuna,
y copia la cookie `vtex_segment` desde las DevTools del navegador (pestaña
Application → Cookies). Sin región, obtienes el catálogo y precios base del
`sales channel` por defecto.

## Alternativa con Scrapy

Si prefieres el framework completo (concurrencia, autothrottle y export gestionados
por Scrapy):

```bash
pip install scrapy
scrapy runspider scrapy_alt/jumbo_spider.py -O productos.csv
```

## Cuándo necesitarías un navegador headless

No para este sitio: la API VTEX no requiere JS. Pero si en el futuro quisieras
datos que solo aparecen renderizados (reseñas dinámicas, widgets), Playwright o
Selenium serían el camino. Quedan comentados en `requirements.txt`.

## Buenas prácticas y consideraciones legales

- Revisa `https://www.jumbo.cl/robots.txt` y los Términos de Servicio del sitio
  antes de ejecutar a gran escala. Este código es para fines legítimos como
  investigación de mercado o monitoreo de precios.
- El scraper incluye **pausas con jitter, reintentos con backoff** y respeta
  códigos 429/5xx. Mantén `--workers` bajo y los delays razonables para no
  sobrecargar el servidor.
- Los datos de catálogo pueden estar sujetos a derechos del titular: úsalos de
  forma responsable y conforme a la normativa aplicable.

## Estructura

```
jumbo_scraper_project/
├── main.py                  # CLI
├── requirements.txt
├── jumbo_scraper/
│   ├── config.py            # parámetros (URLs, delays, paginación)
│   ├── client.py            # sesión HTTP + reintentos + rate-limit
│   ├── categories.py        # árbol de categorías y aplanado a hojas
│   ├── products.py          # paginación por categoría (+ subdivisión por marca)
│   ├── parser.py            # JSON VTEX -> filas planas (una por SKU)
│   ├── storage.py           # escritura incremental CSV / JSONL
│   └── scraper.py           # orquestador + deduplicación
└── scrapy_alt/
    └── jumbo_spider.py      # alternativa con Scrapy
```
