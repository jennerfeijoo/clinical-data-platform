# Guía de estudio: landing zone raw inmutable

## 1. Qué problema resuelve

Antes de esta versión, el pipeline leía directamente el archivo indicado por el usuario:

```text
archivo fuente → parser CSV → validación
```

El reporte almacenaba la ruta y el SHA-256, pero la ruta original podía ser reemplazada, eliminada o editada después. El hash permitía detectar una diferencia solo si todavía existía una copia con la cual comparar; no garantizaba que la plataforma conservara los bytes que realmente recibió.

La landing zone introduce una frontera de ingestión:

```text
archivo recibido
      ↓
captura binaria inmutable
      ↓
objeto content-addressed + receipt
      ↓
parser CSV
      ↓
contrato ejecutable
```

La regla central es:

> La validación nunca trabaja sobre la ubicación externa original. Trabaja sobre la copia raw verificada que la plataforma acaba de capturar.

## 2. Qué significa raw

`raw` significa que los bytes se conservan antes de aplicar transformaciones semánticas.

La capa raw no:

- corrige fechas;
- normaliza categorías;
- elimina filas inválidas;
- reorganiza columnas;
- convierte unidades;
- interpreta el contenido clínico.

Sí registra:

- qué dataset se declaró;
- cuándo se recibió;
- de qué ruta procedía;
- cuál era el nombre del archivo;
- tamaño en bytes;
- tipo de medio;
- SHA-256;
- ubicación inmutable del objeto;
- identificador del receipt.

## 3. Estructura física

La raíz predeterminada es:

```text
data/raw/
```

Su estructura se divide en objetos y receipts:

```text
data/raw/
├── objects/
│   └── sha256/
│       └── ab/
│           └── abcd...7890/
│               └── source.csv
└── receipts/
    └── patients/
        └── 2026/
            └── 07/
                └── 29/
                    └── <receipt-uuid>.json
```

Los artefactos generados están excluidos de Git mediante `data/raw/.gitignore`. No son código fuente; son estado de ejecución.

## 4. Objeto content-addressed

La ruta del objeto deriva de su contenido:

```text
objects/sha256/<primeros-2>/<sha256-completo>/source.csv
```

Ejemplo conceptual:

```text
SHA-256 = abcd1234...

objects/sha256/ab/abcd1234.../source.csv
```

El nombre original no determina la identidad. Dos archivos con nombres diferentes pero bytes idénticos producen el mismo SHA-256 y comparten el mismo objeto.

Esto se denomina almacenamiento direccionado por contenido.

### Consecuencia

```text
mismos bytes → mismo objeto
bytes diferentes → objeto diferente
```

No se utiliza únicamente la fecha o el nombre porque ambos pueden repetirse sin que el contenido sea igual.

## 5. Receipt de ingestión

Un objeto responde:

```text
¿Qué bytes se conservaron?
```

Un receipt responde:

```text
¿Cuándo y bajo qué contexto se recibió ese objeto?
```

Dos recepciones del mismo archivo generan:

```text
1 objeto
2 receipts
```

Esto mantiene deduplicación física sin perder la historia operacional.

Ejemplo de receipt:

```json
{
  "dataset": "patients",
  "media_type": "text/csv",
  "object_path": "objects/sha256/.../source.csv",
  "receipt_id": "...",
  "received_at": "2026-07-29T08:00:00+00:00",
  "sha256": "...",
  "size_bytes": 412,
  "source_filename": "patients.csv",
  "source_path": "C:/.../patients.csv",
  "storage_version": "1.0.0"
}
```

## 6. Inmutabilidad implementada

La implementación combina cuatro mecanismos.

### 6.1 No se abre un artefacto final en modo de sobrescritura

Los objetos y receipts se publican sin reemplazar rutas existentes.

No se utiliza:

```python
open(path, "wb")
```

sobre la ruta final.

### 6.2 Publicación atómica

Los bytes se escriben primero en un archivo temporal dentro del mismo directorio. Después se publica un hard link hacia la ruta final:

```text
staging completo
      ↓
os.link(staging, final)
```

La publicación es atómica: un lector observa el archivo completo o no lo observa. No debe ver una copia parcialmente escrita.

Si la ruta final ya existe, no se reemplaza.

### 6.3 Read-only local

Después de publicar, se aplica permiso `0444`.

Esto reduce modificaciones accidentales, pero no es una garantía absoluta. Un usuario con permisos suficientes puede volver a habilitar escritura.

### 6.4 Verificación criptográfica

Antes de reutilizar o persistir un objeto se recalculan:

```text
SHA-256
size_bytes
```

Si difieren del receipt, la operación falla.

## 7. Qué garantiza y qué no garantiza

### Garantiza dentro del modelo local de la aplicación

- no sobrescritura intencional;
- deduplicación por contenido;
- receipts append-only;
- rutas deterministas;
- detección de corrupción mediante SHA-256;
- captura antes del parsing;
- publicación atómica;
- verificación antes de PostgreSQL.

### No garantiza por sí sola

- almacenamiento WORM certificado;
- protección frente a un administrador del sistema;
- replicación geográfica;
- retención legal;
- cifrado en reposo;
- control de acceso empresarial;
- durabilidad frente a fallo físico del disco;
- cumplimiento regulatorio para PHI.

Una plataforma productiva usaría object storage con versionado, políticas de retención, IAM, cifrado, backups y auditoría externa.

## 8. Flujo de `capture_raw_source`

La función principal está en:

```text
src/clinical_data_platform/raw.py
```

Secuencia:

```text
1. validar nombre del dataset
2. comprobar que el origen es un CSV regular
3. calcular SHA-256 y tamaño
4. derivar la ruta content-addressed
5. copiar a staging y volver a calcular hash
6. publicar atómicamente sin reemplazo
7. crear un receipt UUID append-only
8. devolver rutas y metadatos verificados
```

El hash se calcula antes y durante la copia. Si el archivo cambia mientras se captura, los valores no coinciden y la captura se rechaza.

## 9. Flujo de `verify_raw_receipt`

La verificación no confía ciegamente en el JSON.

Comprueba:

1. que la ruta relativa no escape de `raw_root`;
2. que el receipt sea JSON UTF-8;
3. que sus campos tengan tipos válidos;
4. que el UUID y el timestamp sean parseables;
5. que la ruta del receipt corresponda al dataset, fecha y UUID;
6. que el SHA-256 tenga 64 caracteres hexadecimales;
7. que la ruta del objeto sea la derivada del hash;
8. que el objeto exista;
9. que tamaño y SHA-256 coincidan.

Por eso no basta con editar el JSON para apuntar a otro archivo.

## 10. Integración con el pipeline

La firma actual exige `raw_root`:

```python
run_dataset_validation(
    dataset,
    input_path,
    output_directory,
    raw_root=raw_root,
    reference_date=reference_date,
)
```

La secuencia real es:

```text
input_path externo
      ↓
capture_raw_source
      ↓
raw object verificado
      ↓
read_csv_records(raw_object)
      ↓
contrato
```

Esta decisión es importante: si el archivo original cambia inmediatamente después de la captura, la validación sigue usando la copia capturada.

## 11. Lineage en `quality_report.json`

Cada ejecución registra:

```text
raw_storage_version
raw_receipt_id
raw_received_at
raw_manifest_path
raw_manifest_sha256
raw_object_path
raw_size_bytes
input_sha256
```

`input_sha256` identifica los bytes del objeto raw.

`raw_manifest_sha256` identifica los bytes exactos del receipt.

No son intercambiables:

```text
object hash   → contenido clínico recibido
manifest hash → contexto de recepción
```

## 12. Persistencia y V004

La migración:

```text
V004__add_raw_landing_lineage.sql
```

incorpora estos campos a `audit.pipeline_runs`.

Antes de abrir la transacción de carga, `database.py`:

1. abre el receipt indicado por el quality report;
2. verifica su hash;
3. verifica el objeto;
4. compara dataset, receipt UUID, timestamp, ruta, tamaño y SHA-256;
5. rechaza cualquier inconsistencia;
6. solo entonces persiste el run y los registros clínicos.

Las ejecuciones históricas anteriores a V004 reciben marcadores explícitos `legacy/unmanaged`. No se inventa un receipt que nunca existió.

## 13. Comandos

Captura manual:

```powershell
clinical-data raw-capture patients data/sample/patients.csv `
  --raw-root data/raw
```

Verificación:

```powershell
clinical-data raw-verify `
  receipts/patients/2026/07/29/<uuid>.json `
  --raw-root data/raw
```

Validación integrada:

```powershell
clinical-data validate-dataset patients data/sample/patients.csv `
  --raw-root data/raw `
  --output-dir data/processed/patients `
  --reference-date 2026-07-29
```

Carga integrada:

```powershell
clinical-data load-dataset patients `
  --raw-root data/raw `
  --output-dir data/processed/patients
```

## 14. Por qué el raw root no está dentro de PostgreSQL

Los archivos fuente son objetos binarios completos. Guardarlos directamente en tablas:

- aumenta el tamaño de backups transaccionales;
- mezcla almacenamiento de objetos con modelo relacional;
- dificulta object-level retention;
- obliga a mover bytes grandes por conexiones SQL.

PostgreSQL conserva lineage y estados. El filesystem local conserva los bytes en este proyecto.

En producción, el mismo contrato conceptual podría implementarse sobre S3, Azure Blob o Google Cloud Storage.

## 15. Diferencia entre raw, quarantine y processed

```text
raw
  bytes exactos antes de interpretación

quarantine
  filas interpretadas que incumplen reglas

processed
  filas interpretadas y clasificadas como válidas o inválidas
```

Una fila inválida no se elimina del raw. El raw contiene el archivo completo tal como llegó.

## 16. Preguntas de entrevista

### ¿Por qué usar content addressing?

Porque la identidad del objeto depende de sus bytes, permite deduplicación determinista y hace evidente cualquier cambio de contenido.

### ¿Por qué crear un receipt separado?

Porque una misma secuencia de bytes puede recibirse varias veces, desde rutas o momentos diferentes. El objeto modela contenido; el receipt modela el evento de recepción.

### ¿Por qué validar desde el objeto raw y no desde el original?

Para garantizar que los datos evaluados son exactamente los bytes conservados y auditables.

### ¿Read-only equivale a inmutable?

No de forma absoluta. Es una defensa local contra cambios accidentales. La inmutabilidad fuerte requiere controles del sistema de almacenamiento y permisos externos a la aplicación.

### ¿Qué ocurre si se vuelve a recibir el mismo archivo?

Se reutiliza el objeto content-addressed y se crea un receipt nuevo. No se pierde el evento de recepción.

### ¿Qué ocurre si un objeto existente está corrupto?

La plataforma recalcula su hash y rechaza la operación; no lo reemplaza silenciosamente.

## 17. Ejercicios personales

### Ejercicio 1: inspeccionar una captura

Ejecuta `raw-capture`, localiza el receipt y responde:

- ¿cómo se deriva la ruta del objeto?;
- ¿qué campo identifica el contenido?;
- ¿qué campo identifica la recepción?;
- ¿por qué el nombre original no forma parte de la ruta del objeto?

### Ejercicio 2: demostrar deduplicación

Captura dos veces el mismo CSV.

Comprueba:

```text
mismo object_path
distinto receipt_id
distinto manifest_path
```

### Ejercicio 3: demostrar detección de corrupción

En una copia desechable de la landing zone:

1. vuelve temporalmente escribible el objeto;
2. cambia un byte;
3. ejecuta `raw-verify`;
4. identifica la excepción y el control que falló.

### Ejercicio 4: cambiar el nombre del origen

Copia `patients.csv` como `incoming_001.csv` sin cambiar bytes. Captura ambos.

Explica por qué:

- comparten objeto;
- los receipts conservan nombres distintos.

### Ejercicio 5: añadir soporte para JSON

Diseña, sin implementarlo todavía:

- detección del media type;
- extensión estable del objeto;
- validación del contrato;
- compatibilidad de `storage_version`;
- pruebas necesarias.

### Ejercicio 6: explicar el riesgo de una escritura directa

Describe el fallo concurrente que ocurriría si un proceso creara la ruta final y otro la leyera mientras todavía estaba copiándose. Explica cómo staging + publicación atómica evita ese estado parcial.

## 18. Criterio de dominio

Has comprendido este bloque cuando puedes explicar y modificar sin ayuda:

```text
source file
→ SHA-256
→ staging
→ atomic publish
→ content object
→ append-only receipt
→ verified validation
→ quality report
→ PostgreSQL lineage
```

También debes poder distinguir claramente:

```text
inmutabilidad lógica
permisos read-only
integridad criptográfica
publicación atómica
deduplicación
retención
```

Son propiedades relacionadas, pero no equivalentes.
