# Guía de estudio: dataset Synthea reproducible

## Objetivo

Este hito reemplaza la idea de «descargar algunos CSV sintéticos» por una cadena verificable:

```text
perfil versionado
→ release upstream fijada
→ semillas y fecha de referencia
→ generación CSV
→ manifiesto de procedencia
→ adaptación determinista
→ contratos ejecutables
→ terminología local
→ raw inmutable
→ PostgreSQL y auditoría
```

La meta no es demostrar que Synthea reproduce una población real. La meta es poder explicar exactamente cómo se obtuvo un dataset sintético y detectar cuándo dos ejecuciones no produjeron los mismos artefactos.

## 1. Qué significa reproducibilidad aquí

Una generación queda definida por:

```text
versión de Synthea
commit upstream
semilla poblacional
semilla de clínicos
número de pacientes
fecha de referencia
geografía
número de threads
historia retenida
exportadores activados
archivos CSV incluidos
```

No basta con escribir «usamos Synthea». Dos ejecuciones pueden diferir si cambia cualquiera de esos controles.

## 2. Perfil empaquetado

El archivo:

```text
src/clinical_data_platform/synthea_profiles/reproducible_small.toml
```

fija:

```text
Synthea v4.0.0
100 pacientes
seed 20260729
clinician seed 20260730
reference date 2026-07-29
Massachusetts
1 thread
historia completa
seis CSV
```

El perfil también tiene su propio SHA-256. Por tanto, el manifiesto puede demostrar qué bytes de configuración fueron usados.

## 3. Por qué se fija un solo thread

La generación paralela puede modificar el orden en que se completan y exportan registros. Aunque los resultados clínicos agregados puedan parecer equivalentes, los CSV y ciertos identificadores dependientes de la ejecución pueden no ser byte a byte iguales.

El perfil utiliza:

```text
generate.thread_pool_size = 1
```

No es una optimización de rendimiento. Es una decisión de control experimental.

## 4. Dos semillas distintas

Synthea acepta:

```text
-s  → random seed
-cs → clinician seed
```

La primera controla la simulación de pacientes. La segunda controla la generación de clínicos. Fijar solo una deja una fuente de variación abierta.

## 5. Fecha de referencia

La opción:

```text
-r 20260729
```

fija el instante de corte de la simulación. Sin ella, una ejecución futura podría producir edades, muertes, eventos o duraciones diferentes aunque usara la misma semilla.

## 6. Identidad upstream

El perfil declara:

```text
ref = v4.0.0
```

El workflow verifica además:

```text
git describe --tags --exact-match
git rev-parse HEAD
git status --porcelain
```

Así se distinguen:

```text
nombre de la release
commit exacto
checkout limpio o modificado
```

El commit real queda escrito en el manifiesto de generación.

## 7. Esquema fuente fijado

El adaptador espera exactamente los encabezados CSV publicados por Synthea 4.0.0 para:

```text
patients.csv
encounters.csv
conditions.csv
observations.csv
medications.csv
procedures.csv
```

Si upstream añade, elimina, renombra o reordena una columna, el proceso falla con schema drift.

Esto obliga a revisar conscientemente una nueva versión del adaptador en vez de interpretar por accidente un formato diferente.

## 8. Manifiesto de generación

Después de generar, se calcula para cada archivo:

```text
nombre
header
row_count
size_bytes
sha256
```

El `dataset_fingerprint` resume:

```text
profile_sha256
upstream_commit
fingerprints de los seis CSV
```

Dos generaciones son byte-identical solo cuando coinciden los hashes de los seis archivos y el fingerprint global.

## 9. Adaptación, no copia

Los CSV de Synthea no coinciden directamente con los contratos internos. El adaptador realiza transformaciones explícitas.

### Pacientes

```text
Id        → patient_id
GENDER    → sex_at_birth
BIRTHDATE → birth_date
DEATHDATE → death_date
```

`GENDER` no es semánticamente idéntico a sex-at-birth en todos los contextos. El adaptador documenta esta aproximación y solo conserva `F`, `M` o `UNKNOWN`.

### Encuentros

```text
inpatient → INPATIENT
emergency → EMERGENCY
otros      → OUTPATIENT
```

### Condiciones

`conditions.csv` se convierte en `diagnoses.csv`. Como la fila no tiene un identificador de evento estable, se genera un UUIDv5 determinista.

### Observaciones

Solo se aceptan:

```text
8480-6 → SYSTOLIC_BP
8462-4 → DIASTOLIC_BP
8867-4 → HEART_RATE
```

Los demás registros se cuentan como omitidos. No se presentan como errores de Synthea: están fuera del alcance del contrato actual.

### Medicamentos

La columna `CODE` se interpreta como RxNorm porque el CSV de medicamentos no incluye una columna de sistema. El estado se deriva de la presencia de `STOP`.

### Procedimientos

Los sistemas soportados se normalizan a:

```text
SNOMED
CPT
ICD10PCS
```

## 10. UUIDv5 determinista

Para entidades sin ID fuente se utiliza:

```text
namespace fijo
+ dataset
+ archivo fuente
+ número de fila
+ contenido canónico de la fila
→ UUIDv5
```

Propiedad:

```text
misma fila y misma posición → mismo ID
contenido distinto          → ID distinto
```

No es un identificador clínico universal. Es una identidad técnica reproducible para este adapter versionado.

## 11. Integridad de padres

Una fila dependiente solo se conserva cuando:

```text
patient_id existe
encounter_id existe
encounter.patient_id == event.patient_id
```

Esto evita producir diagnósticos, observaciones, medicamentos o procedimientos huérfanos antes de llegar a PostgreSQL.

## 12. Terminología dinámica controlada

Synthea puede producir muchos códigos que no están en el pequeño catálogo local del proyecto.

El adaptador crea `terminology.csv` con:

```text
code_system
code
display
domain
verification_status
source_reference
```

Los conceptos ausentes se insertan como:

```text
verification_status = unverified
```

Esto permite cargar el dataset sin afirmar que cada código fue contrastado independientemente con una release oficial.

## 13. Contratos después del adapter

Antes de escribir el manifiesto final, las seis colecciones adaptadas pasan por los contratos activos.

La regla es:

```text
adapter produce datos conformes
```

No:

```text
adapter produce datos aproximados y el pipeline descarta lo que falle
```

Una infracción contractual del output adaptado detiene todo el proceso.

## 14. Manifiesto de adaptación

Registra:

```text
adapter_version
profile_sha256
source files
output files
row counts
omitted reasons
terminology count
adaptation fingerprint
```

El fingerprint incluye tanto entradas como salidas. Modificar un CSV normalizado después de la adaptación hace fallar `synthea-verify`.

## 15. Flujo completo

```powershell
.\scripts\generate_synthea.ps1
```

Equivale conceptualmente a:

```text
synthea-profile
synthea-generate
synthea-adapt
synthea-verify
```

La carga posterior es:

```powershell
clinical-data synthea-load `
  data/synthea/synthea-us-small-v1/normalized `
  --processed-root data/processed/synthea `
  --raw-root data/raw
```

## 16. Qué reutiliza `synthea-load`

No existe un pipeline de carga paralelo. Cada CSV normalizado pasa por:

```text
raw capture
contrato activo
validación
quality report
journal local
registro durable
terminología
persistencia transaccional
logging estructurado
```

Esto demuestra que Synthea es una nueva fuente, no una segunda arquitectura.

## 17. Qué prueba CI

CI usa un fixture pequeño con el esquema oficial esperado. Prueba:

```text
perfil empaquetado
comando determinista
schema drift
adaptación repetible
tamper detection
contratos
terminología
carga PostgreSQL completa
```

No ejecuta el generador Java completo. Esa decisión evita que cada PR dependa de red, clone upstream y compilación Gradle.

## 18. Preguntas que debes poder responder

1. ¿Por qué una seed no basta para definir completamente la generación?
2. ¿Por qué se fija la fecha de referencia?
3. ¿Por qué un tag y un commit no representan exactamente lo mismo?
4. ¿Qué problema reduce el thread pool igual a uno?
5. ¿Qué contiene el generation manifest?
6. ¿Por qué el adapter valida los headers exactos?
7. ¿Por qué las condiciones necesitan UUIDv5?
8. ¿Por qué solo se conservan tres observaciones?
9. ¿Qué diferencia hay entre una fila omitida y una fila inválida?
10. ¿Por qué los nuevos conceptos se marcan `unverified`?
11. ¿Por qué `synthea-load` no necesita un pipeline especial?
12. ¿Qué evidencia permite comparar dos generaciones?

## 19. Ejercicios

### Ejercicio 1: cambiar la seed

Copia el perfil y cambia:

```text
random_seed = 20260731
```

Explica qué hashes deben cambiar incluso antes de generar.

### Ejercicio 2: schema drift

Renombra `BIRTHDATE` a `DATE_OF_BIRTH` en un fixture.

Verifica que la adaptación falle antes de procesar pacientes.

### Ejercicio 3: tampering

Modifica una línea de `patients.csv` después de crear el manifiesto de adaptación.

Ejecuta:

```powershell
clinical-data synthea-verify <directorio>
```

Explica qué comprobación falla.

### Ejercicio 4: nueva observación

Diseña soporte para peso corporal LOINC `29463-7`.

Enumera los cambios necesarios en:

```text
contrato de observations
measurement profile
adapter
terminología
pruebas
documentación
```

### Ejercicio 5: reproducibilidad real

Ejecuta la generación dos veces en directorios separados con el mismo perfil.

Compara:

```text
upstream_commit
profile_sha256
file SHA-256
dataset_fingerprint
```

No concluyas que son idénticas solo porque tienen el mismo número de filas.

## 20. Explicación profesional

> La plataforma utiliza un perfil Synthea empaquetado que fija release, commit verificable, semillas, fecha de referencia, población, geografía, número de threads y opciones del exporter. La generación produce un manifiesto con hashes, tamaños, headers y conteos de los seis CSV. Un adapter versionado convierte ese esquema a los seis contratos internos, genera IDs UUIDv5 cuando el origen no provee identidad, contabiliza exclusiones y produce un segundo manifiesto con fingerprint de entradas y salidas. Los códigos nuevos se importan como conceptos no verificados y los datasets continúan por el pipeline genérico existente.

## 21. Límite actual

La población de 100 pacientes es adecuada para demostrar procedencia y reproducibilidad, no para benchmarks significativos. El próximo hito deberá utilizar `COPY`, staging y medición de throughput con una población mayor y un protocolo de benchmark explícito.
