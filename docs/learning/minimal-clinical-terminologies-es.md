# Guía de estudio: terminologías clínicas mínimas integradas

## Objetivo del hito

Antes de V007, el repositorio almacenaba campos como:

```text
code_system = ICD10
diagnosis_code = I10
```

pero la base de datos no comprobaba que:

- `ICD10` correspondiera a un sistema registrado;
- `I10` estuviera incluido en un catálogo conocido;
- el código perteneciera al dominio diagnóstico;
- un código local tuviera una representación estándar;
- el sistema y su versión quedaran documentados.

V007 introduce una capa terminológica mínima para resolver esas limitaciones sin afirmar que el proyecto contiene terminologías completas.

## 1. Tres niveles diferentes

### Código fuente

Es exactamente lo que llega desde el sistema productor.

```text
source_system = LOCAL_OBSERVATION
source_code = SYSTOLIC_BP
```

Debe conservarse porque forma parte del lineage y permite reconstruir lo recibido.

### Sistema canónico

Normaliza nombres alternativos del sistema.

```text
ICD10  → ICD10CM
SNOMED → SNOMEDCT
```

Esto evita que variaciones de nombres se conviertan en sistemas diferentes dentro de la base.

### Concepto normalizado

Es el concepto interno al que queda enlazada la fila clínica.

```text
LOCAL_OBSERVATION:SYSTOLIC_BP
→ LOINC:8480-6
→ Systolic blood pressure
```

La fila mantiene el código fuente, pero recibe además `normalized_concept_id`.

## 2. Modelo relacional

```text
terminology.code_systems
        │
        ├── terminology.system_aliases
        │
        └── terminology.concepts
                    │
                    └── terminology.concept_mappings
```

### `code_systems`

Registra:

```text
identificador local
URI canónica
autoridad
versión upstream
versión del subconjunto
si es una distribución completa
nota de licencia
```

### `system_aliases`

Convierte nombres de entrada a un identificador canónico.

### `concepts`

Registra:

```text
sistema
código
display
dominio
estado activo
estado de verificación
referencia de origen
```

### `concept_mappings`

Relaciona un concepto fuente con uno objetivo e incluye:

```text
equivalence
mapping_version
review_status
mapping_method
```

## 3. Sistemas incluidos

El subconjunto registra:

```text
ICD10CM
LOINC
RXNORM
ATC
SNOMEDCT
CPT
ICD10PCS
LOCAL_OBSERVATION
```

No significa que el repositorio contenga cada sistema completo.

La columna `complete_release` solo es verdadera para `LOCAL_OBSERVATION`, porque ese sistema fue creado dentro del proyecto y contiene todos sus códigos actuales.

## 4. Mapeo de observaciones locales

Los datos sintéticos ya utilizaban:

```text
SYSTOLIC_BP
DIASTOLIC_BP
HEART_RATE
```

V007 los conserva y agrega estos mapeos:

```text
SYSTOLIC_BP  → LOINC 8480-6
DIASTOLIC_BP → LOINC 8462-4
HEART_RATE   → LOINC 8867-4
```

Esto permite distinguir:

```text
lo que envió la fuente
versus
el concepto utilizado para análisis e interoperabilidad local
```

## 5. Dominios

Cada concepto pertenece a un dominio:

```text
condition
observation
medication
procedure
```

Las tablas clínicas esperan:

```text
diagnoses    → condition
observations → observation
medications  → medication
procedures   → procedure
```

Un código puede existir en el catálogo y aun así ser inválido para una tabla si pertenece a otro dominio.

## 6. Función de resolución

La función central es:

```sql
terminology.resolve_concept(
    source_system,
    source_code,
    expected_domain
)
```

Su secuencia es:

```text
1. validar que sistema y código no estén vacíos
2. resolver el alias del sistema
3. localizar el concepto fuente
4. aplicar un mapping cuando existe
5. comprobar que el concepto esté activo
6. comprobar el dominio
7. devolver concept_id
```

## 7. Integración con las tablas clínicas

V007 añade:

```text
normalized_concept_id
```

a:

```text
clinical.diagnoses
clinical.observations
clinical.medications
clinical.procedures
```

El campo es:

```text
NOT NULL
+ foreign key a terminology.concepts
```

Por tanto, ninguna fila codificada aceptada puede quedar sin concepto normalizado.

## 8. Triggers antes de la inmutabilidad

Cada tabla recibe un trigger terminológico `BEFORE INSERT OR UPDATE`.

Ejemplo:

```text
INSERT diagnosis
→ resolver ICD10:I10
→ asignar normalized_concept_id
→ calcular record_sha256
→ comprobar inmutabilidad
→ insertar
```

El nombre `trg_00_...` hace que el trigger terminológico se ejecute antes del guard de inmutabilidad del mismo tipo y momento.

## 9. Contrato versus terminología

El contrato de diagnósticos puede comprobar:

```text
code_system pertenece a una lista
el código no está vacío
la fecha es válida
```

No contiene una lista completa de códigos.

Por eso una fila como:

```text
code_system = ICD10
diagnosis_code = ZZZ.999
```

puede superar el contrato estructural, pero debe fallar al persistir porque el concepto no existe en el subconjunto terminológico.

Esta separación es deliberada:

```text
contrato → forma y validez intrínseca del archivo
terminología → significado codificado reconocido
PostgreSQL → integridad relacional y transaccional
```

## 10. Rollback de un código desconocido

Cuando aparece un código desconocido:

```text
validación del CSV completada
→ inicia la transacción de carga
→ trigger intenta resolver el concepto
→ concepto desconocido
→ error de integridad
→ rollback completo de la carga
```

Se conserva:

```text
raw object
raw receipt
processed outputs
quality report
```

No se conserva:

```text
fila clínica parcial
pipeline_run pendiente en PostgreSQL
```

## 11. Compatibilidad al actualizar V006 a V007

Una base V006 puede contener códigos aceptados antes de existir la capa terminológica.

V007 importa esos códigos cuando no están en el subconjunto inicial y los marca como:

```text
verification_status = unverified
```

Esto evita dos errores opuestos:

- bloquear una actualización por datos previamente válidos;
- declarar esos códigos como verificados sin evidencia.

Después de V007, los códigos nuevos sí deben existir en el catálogo instalado.

## 12. Estados de verificación

### `verified`

El código y el display local se contrastaron con una fuente identificada.

### `curated`

El concepto fue creado deliberadamente por el proyecto, como los códigos locales de observación.

### `unverified`

El código se conserva por compatibilidad o se representa sin descriptor externo verificado.

Este estado no determina si el código fue clínicamente apropiado para un paciente. Solo describe la evidencia del registro terminológico local.

## 13. Restricciones de licencia

No todas las terminologías pueden redistribuirse de la misma manera.

El diseño aplica límites explícitos:

```text
LOINC      → pequeño subconjunto con versión
SNOMED CT  → entradas ilustrativas, no release completo
CPT        → códigos y labels neutrales; no descriptores licenciados
ATC        → subconjunto ilustrativo
ICD        → códigos necesarios para los datos sintéticos
RxNorm     → conceptos usados por la muestra
```

Una plataforma seria debe gestionar licencias, versiones, artefactos fuente y actualizaciones como parte del lifecycle terminológico.

## 14. Vista de inspección

```sql
SELECT
    dataset_name,
    entity_id,
    source_system,
    source_code,
    normalized_system,
    normalized_code,
    normalized_display,
    domain,
    verification_status
FROM terminology.normalized_clinical_codes
ORDER BY dataset_name, entity_id;
```

Esta vista permite auditar simultáneamente:

```text
representación fuente
representación normalizada
dominio
estado de verificación
```

## 15. API Python

```python
from clinical_data_platform.terminology import (
    list_terminology_systems,
    resolve_terminology_concept,
    validate_terminology_bindings,
)
```

### Resolver un concepto

```python
concept = resolve_terminology_concept(
    connection,
    "LOCAL_OBSERVATION",
    "SYSTOLIC_BP",
    "observation",
)
```

Resultado esperado:

```text
system = LOINC
code = 8480-6
domain = observation
```

### Validar toda la base

```python
summary = validate_terminology_bindings(connection)
```

Comprueba que todas las filas codificadas tengan:

```text
concepto existente
concepto activo
dominio correcto
```

## 16. Preguntas que debes poder responder

1. ¿Por qué conservar el código fuente después de normalizarlo?
2. ¿Qué diferencia existe entre alias de sistema y concept mapping?
3. ¿Por qué `ICD10 → ICD10CM` no cambia automáticamente el código?
4. ¿Por qué una fila puede pasar el contrato y fallar al persistir?
5. ¿Qué garantiza `normalized_concept_id NOT NULL`?
6. ¿Por qué las observaciones locales se mapean a LOINC?
7. ¿Qué significa `verification_status = unverified`?
8. ¿Por qué no se distribuyen descriptores CPT?
9. ¿Qué ocurre con códigos que ya estaban almacenados en V006?
10. ¿Por qué esta implementación no es un servidor terminológico completo?

## 17. Ejercicios

### Ejercicio 1: resolver un diagnóstico

Busca `ICD10:I10` mediante la API Python y confirma:

```text
normalized system = ICD10CM
normalized code = I10
domain = condition
```

### Ejercicio 2: código desconocido

Cambia temporalmente `D001.diagnosis_code` por `ZZZ.999`.

Comprueba:

```text
contrato aceptado
persistencia rechazada
diagnoses = 0 después del rollback
pipeline_run conflictivo = 0
raw receipt permanece
```

### Ejercicio 3: dominio incorrecto

Intenta resolver:

```text
LOINC:8480-6
expected_domain = medication
```

Explica por qué el código existe pero la resolución debe fallar.

### Ejercicio 4: nueva observación local

Diseña:

```text
BODY_TEMPERATURE
```

Enumera lo que debes añadir:

```text
contrato de observations
concepto LOCAL_OBSERVATION
concepto objetivo
mapping versionado
unidad y rango plausibles
pruebas
```

### Ejercicio 5: importar una release

Diseña conceptualmente un loader de terminologías que registre:

```text
source artifact SHA-256
release version
license metadata
import run ID
rows received
rows accepted
rows rejected
activation/deactivation changes
```

No lo implementes como una edición manual de V007; debe ser un pipeline independiente y versionado.

## 18. Explicación profesional

> La plataforma incorpora una capa terminológica mínima en PostgreSQL. Conserva códigos fuente, normaliza aliases de sistemas y vincula diagnósticos, observaciones, medicamentos y procedimientos con conceptos activos y tipados por dominio. Los códigos locales de presión arterial y frecuencia cardiaca se mapean a LOINC. La carga rechaza transaccionalmente sistemas, códigos o dominios desconocidos. El catálogo es deliberadamente pequeño y versionado; no se presenta como una distribución completa ni como un servidor terminológico de producción.

## 19. Límite actual

Todavía faltan:

```text
importadores de releases
sincronización upstream
jerarquías y subsunción
sinónimos y traducciones
UCUM
mappings contextuales o muchos-a-muchos
historial temporal de mappings
FHIR terminology operations
validación clínica del código elegido
```

El siguiente hito del roadmap es completar estados de ejecución y logging estructurado, no ampliar manualmente el catálogo dentro de otra migración.
