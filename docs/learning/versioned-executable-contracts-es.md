# Guía de estudio: contratos ejecutables y versionados

## 1. Qué problema resuelve este cambio

Antes de este refactor, las reglas estructurales estaban codificadas directamente en Python:

- nombres y orden de columnas;
- valores obligatorios;
- claves únicas;
- categorías permitidas;
- tipos de fecha, fecha-hora y número;
- rangos plausibles de mediciones.

La documentación Markdown describía parte de esas reglas, pero no las ejecutaba. Esto generaba dos fuentes de verdad:

```text
Documentación humana
        ≠
Código de validación
```

Si una persona actualizaba una columna en la documentación y olvidaba modificar Python, ambas versiones podían divergir sin que el sistema lo detectara.

La nueva arquitectura establece esta relación:

```text
Contrato TOML versionado
        │
        ├── describe el dataset
        ├── es validado al cargarse
        ├── ejecuta reglas sobre los datos
        ├── determina las columnas de salida
        └── deja lineage en el quality report y PostgreSQL
```

## 2. Qué significa “contrato de datos”

Un contrato de datos es un acuerdo explícito entre quien produce un dataset y quien lo consume.

En este repositorio, el contrato define:

- nombre del dataset;
- versión semántica;
- clave primaria;
- columna que identifica al paciente;
- columnas permitidas;
- orden de columnas;
- tipo de cada columna;
- obligatoriedad;
- unicidad;
- valores categóricos admitidos;
- reglas temporales;
- perfiles de medición, unidades y rangos plausibles.

No es solamente documentación. El pipeline lo carga y lo ejecuta.

## 3. Organización de los contratos

Los contratos viven dentro del paquete:

```text
src/clinical_data_platform/contracts/
├── __init__.py
├── manifest.toml
├── patients/
│   └── v1.0.0.toml
├── encounters/
│   └── v1.0.0.toml
├── diagnoses/
│   └── v1.0.0.toml
└── observations/
    └── v1.0.0.toml
```

El archivo `manifest.toml` selecciona la versión activa:

```toml
schema_version = "1.0.0"

[contracts]
patients = "patients/v1.0.0.toml"
encounters = "encounters/v1.0.0.toml"
diagnoses = "diagnoses/v1.0.0.toml"
observations = "observations/v1.0.0.toml"
```

El manifest evita que el código tenga que decidir manualmente qué versión está vigente.

## 4. Ejemplo: contrato de pacientes

```toml
not_future_fields = ["birth_date"]

[dataset]
name = "patients"
version = "1.0.0"
primary_key = "patient_id"
patient_id_column = "patient_id"
allow_extra_columns = false

[[order_rules]]
earlier_field = "birth_date"
later_field = "death_date"

[[columns]]
name = "patient_id"
type = "string"
required = true
unique = true
```

Este fragmento significa:

1. `patient_id` identifica de manera única cada fila.
2. No puede estar vacío.
3. No se admiten columnas que no estén declaradas.
4. `birth_date` no puede estar en el futuro.
5. `death_date`, cuando existe, no puede preceder a `birth_date`.

## 5. Ejemplo: perfiles de observaciones

```toml
[measurement]
code_field = "observation_code"
value_field = "value_numeric"
unit_field = "unit"

[[measurement.profiles]]
code = "SYSTOLIC_BP"
unit = "mmHg"
minimum = 50.0
maximum = 300.0
```

El motor interpreta esta configuración de forma condicional:

```text
Si observation_code == SYSTOLIC_BP:
    unit debe ser mmHg
    value_numeric debe estar entre 50 y 300
```

La regla ya no está dispersa en un bloque `if` exclusivo para observaciones.

## 6. Flujo de ejecución

Cuando se ejecuta:

```powershell
clinical-data validate-dataset patients data/sample/patients.csv `
  --output-dir data/processed/patients `
  --reference-date 2026-07-29
```

ocurre lo siguiente:

```text
1. CLI recibe "patients"
2. registry.py obtiene DatasetDefinition
3. contract.py consulta manifest.toml
4. manifest selecciona patients/v1.0.0.toml
5. el contrato se parsea con tomllib
6. se verifica su consistencia interna
7. se calcula SHA-256 de los bytes del contrato
8. el CSV se valida contra las reglas declaradas
9. pipeline.py escribe válidos, inválidos y errores
10. quality_report.json registra versión, ruta y hash del contrato
11. database.py vuelve a verificar el contrato antes de persistir
12. audit.pipeline_runs conserva su lineage
```

## 7. Responsabilidades de los módulos

### `contract.py`

Responsabilidades:

- cargar el manifest;
- cargar contratos TOML;
- validar la definición del contrato;
- convertir TOML en dataclasses;
- ejecutar reglas sobre registros;
- calcular el hash del contrato.

No conoce SQL ni detalles de conexión a PostgreSQL.

### `registry.py`

Conserva únicamente comportamiento que no debe representarse como configuración libre:

- conversión de filas validadas a tipos de PostgreSQL;
- sentencia SQL de upsert.

Las columnas y claves ya no se definen en el registro. Se consultan desde el contrato.

### `pipeline.py`

Orquesta:

- lectura;
- ejecución del contrato;
- escritura de outputs;
- generación del reporte de calidad.

No contiene reglas clínicas específicas.

### `database.py`

Antes de cargar datos:

- abre el quality report;
- carga el contrato histórico indicado por `contract_path`;
- comprueba el nombre del dataset;
- comprueba `contract_version`;
- recalcula y compara `contract_sha256`;
- rechaza outputs cuyo lineage contractual sea inconsistente.

## 8. Por qué se usa TOML

TOML fue elegido porque:

- Python 3.11 incluye `tomllib` en la biblioteca estándar;
- no añade una dependencia de parsing;
- es legible para humanos;
- permite tablas y arrays de tablas;
- es apropiado para configuración versionada.

No significa que TOML sea universalmente superior. JSON Schema, YAML, Pydantic y Pandera también serían opciones razonables según el contexto.

## 9. Qué significa versionar un contrato

La versión sigue la forma:

```text
MAJOR.MINOR.PATCH
```

### PATCH

Corrección que no cambia qué datos son aceptados, por ejemplo una descripción o metadato no ejecutado.

### MINOR

Cambio compatible hacia atrás, por ejemplo añadir una columna opcional.

### MAJOR

Cambio incompatible, por ejemplo:

- renombrar una columna;
- convertir una columna opcional en obligatoria;
- cambiar el tipo de una columna;
- eliminar un valor categórico antes permitido;
- modificar la clave primaria.

Ejemplo:

```text
patients/v1.0.0.toml
patients/v1.1.0.toml
patients/v2.0.0.toml
```

Los contratos anteriores no deben sobrescribirse. Deben conservarse para reproducir ejecuciones históricas.

## 10. Por qué se registra un hash además de la versión

Una versión como `1.0.0` es una etiqueta declarada por una persona. No garantiza por sí sola que el archivo no haya cambiado.

El SHA-256 identifica los bytes exactos:

```text
contract_version = significado declarado
contract_sha256 = contenido exacto ejecutado
```

Si alguien modifica `v1.0.0.toml` sin cambiar su versión, el hash cambia. Las nuevas ejecuciones registrarán el nuevo hash y el problema será visible.

La política correcta sigue siendo no modificar contratos publicados.

## 11. Quality report

Cada ejecución incorpora:

```json
{
  "contract_path": "patients/v1.0.0.toml",
  "contract_version": "1.0.0",
  "contract_sha256": "..."
}
```

Esto permite responder:

- ¿qué reglas exactas evaluaron el archivo?;
- ¿qué versión estaba activa?;
- ¿el archivo de contrato fue modificado?;
- ¿puedo reproducir la validación?

## 12. Lineage en PostgreSQL

`audit.pipeline_runs` conserva:

```text
source_path
source_sha256
contract_path
contract_version
contract_sha256
reference_date
row counts
status
timestamps
```

El lineage enlaza tres elementos:

```text
Código + contrato + archivo fuente
```

El repositorio todavía no registra el commit Git; eso se añadirá en una etapa posterior.

## 13. Comandos de inspección

Listar contratos activos:

```powershell
clinical-data list-contracts
```

Mostrar un contrato interpretado:

```powershell
clinical-data show-contract observations
```

Validar todas las definiciones:

```powershell
clinical-data validate-contracts
```

Estos comandos permiten revisar contratos sin ejecutar una carga completa.

## 14. Qué errores detecta el motor

Reglas genéricas:

```text
required_column
unexpected_column
required_value
unique
allowed_values
iso_date
iso_datetime
numeric
```

Reglas declarativas adicionales:

```text
not_in_future
temporal_consistency
unit_consistency
plausible_range
```

Una fila puede generar varios errores. Por eso el número de errores puede ser mayor que el número de filas inválidas.

## 15. Decisiones y límites

### Decisión: contratos dentro del paquete

Ventaja: están disponibles después de instalar el proyecto y dentro de la imagen Docker.

Costo: para añadir contratos se debe construir una nueva versión del paquete.

### Decisión: mantener SQL fuera del contrato

El contrato describe la interfaz de datos. El SQL de persistencia sigue en código porque ejecutar SQL arbitrario desde configuración aumentaría el riesgo y dificultaría el tipado.

### Decisión: versionar por archivo

Las versiones históricas se conservan como archivos separados. El manifest solo cambia cuál es la activa.

### Límite actual

El motor soporta cuatro tipos básicos y un conjunto controlado de reglas. No pretende ser un lenguaje de validación universal.

## 16. Cómo añadir una versión compatible

Ejemplo: añadir `preferred_language` opcional a pacientes.

1. Copia:

```text
patients/v1.0.0.toml
→ patients/v1.1.0.toml
```

2. Cambia:

```toml
version = "1.1.0"
```

3. Añade:

```toml
[[columns]]
name = "preferred_language"
type = "string"
required = false
unique = false
```

4. Actualiza el manifest:

```toml
patients = "patients/v1.1.0.toml"
```

5. Actualiza los fixtures, el esquema y el row builder cuando sea necesario.

6. Ejecuta:

```powershell
clinical-data validate-contracts
python -m pytest
```

## 17. Cómo introducir un cambio incompatible

Ejemplo: reemplazar `sex_at_birth` por otra estructura no compatible.

Eso requiere:

```text
patients/v2.0.0.toml
```

Además del nuevo contrato, probablemente requiere:

- migración de base de datos;
- adaptación del row builder;
- estrategia para datos históricos;
- actualización de cohortes;
- documentación de compatibilidad.

Cambiar el manifest sin estas medidas sería insuficiente.

## 18. Preguntas de entrevista

### ¿Por qué el contrato es ejecutable?

Porque el pipeline no solo lo muestra: lo carga y utiliza sus reglas para decidir qué filas son válidas.

### ¿Cómo se reproduce una validación histórica?

Con el archivo fuente identificado por `source_sha256`, el contrato identificado por `contract_path`, `contract_version` y `contract_sha256`, la fecha de referencia y la versión correspondiente del código.

### ¿Por qué no guardar únicamente la versión?

Porque una etiqueta puede reutilizarse o modificarse incorrectamente. El hash representa los bytes exactos.

### ¿Por qué no colocar el SQL dentro del TOML?

Porque el SQL es comportamiento con implicaciones de seguridad, tipado y transacciones. Mantenerlo en código reduce la superficie de configuración ejecutable.

### ¿Qué diferencia hay entre schema y data contract?

El schema describe principalmente estructura y tipos. El contrato también incorpora expectativas de calidad, semántica, versionado, ownership y compatibilidad.

## 19. Ejercicios personales

### Ejercicio 1

Ejecuta `show-contract observations` y explica cada campo sin leer esta guía.

### Ejercicio 2

Cambia temporalmente el máximo de presión sistólica a `250`. Predice qué filas cambiarían de estado y compruébalo.

### Ejercicio 3

Añade una columna extra al CSV de pacientes. Explica por qué se genera `unexpected_column`.

### Ejercicio 4

Modifica una copia de `quality_report.json` y cambia `contract_sha256`. Ejecuta la persistencia y explica por qué se rechaza.

### Ejercicio 5

Crea `patients/v1.1.0.toml` con una columna opcional. No modifiques `v1.0.0.toml`.

### Ejercicio 6

Dibuja la diferencia entre:

```text
manifest version
contract version
contract hash
source hash
pipeline run UUID
```

## 20. Criterio de dominio

Puedes considerar que comprendes este hito cuando puedas:

- explicar por qué existía duplicación antes;
- seguir una fila desde el TOML hasta PostgreSQL;
- justificar el manifest;
- crear una nueva versión sin sobrescribir la anterior;
- distinguir cambio compatible e incompatible;
- explicar por qué se conserva el hash;
- diagnosticar un contrato inválido;
- modificar una regla y actualizar sus pruebas;
- defender qué permanece en código y qué se mueve a configuración.

El objetivo no es memorizar cada línea. Es comprender la separación entre interfaz declarada, motor de ejecución, persistencia y lineage.
