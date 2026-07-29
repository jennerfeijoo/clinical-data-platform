# Guía de estudio: arquitectura genérica de datasets

## Propósito

Esta guía explica el refactor que eliminó el pipeline especial para pacientes. No está pensada para que memorices archivos, sino para que puedas:

- explicar el problema arquitectónico original;
- justificar la solución adoptada;
- seguir el recorrido completo de una ejecución;
- añadir un dataset sin modificar el pipeline;
- diagnosticar errores;
- realizar cambios específicos sin depender de IA.

## 1. El problema original

El repositorio tenía dos caminos de ejecución:

```text
patients
  ├── run_patient_validation()
  └── persist_patient_validation_outputs()

encounters / diagnoses / observations
  ├── run_entity_validation()
  └── persist_entity_validation_outputs()
```

Aunque ambos caminos realizaban casi las mismas etapas, estaban implementados en módulos distintos:

```text
pipeline.py
entity_pipeline.py

database.py
entity_database.py
```

Esto generaba cuatro problemas.

### 1.1 Duplicación

Los dos pipelines calculaban checksum, generaban UUID, leían CSV, escribían archivos válidos e inválidos, producían errores y generaban un reporte JSON.

### 1.2 Tratamiento excepcional de pacientes

`patients` era conceptualmente otro dataset registrado, pero la arquitectura lo trataba como una excepción. Cada nueva capacidad debía decidir si se implementaba en el camino de pacientes, en el camino de entidades o en ambos.

### 1.3 Riesgo de divergencia

Dos implementaciones inicialmente equivalentes tienden a evolucionar de forma diferente. Por ejemplo, un cambio en el formato de errores podía aplicarse a un pipeline y olvidarse en el otro.

### 1.4 Extensión costosa

Añadir `medications` habría requerido modificar varias ramas condicionales y posiblemente crear más funciones específicas.

## 2. La decisión arquitectónica

El refactor separa dos tipos de conocimiento:

```text
Lo que nunca cambia entre datasets
vs.
Lo que sí cambia entre datasets
```

### Comportamiento invariante

Todos los datasets:

1. se identifican por nombre;
2. se leen desde CSV;
3. se validan;
4. producen registros válidos e inválidos;
5. producen errores normalizados;
6. generan un checksum y un `run_id`;
7. escriben un reporte de calidad;
8. se cargan transaccionalmente;
9. registran lineage.

Ese comportamiento vive en:

```text
pipeline.py
database.py
```

### Comportamiento variable

Cada dataset cambia en:

- columnas;
- identificador principal;
- reglas de validación;
- conversión de strings a tipos Python;
- sentencia SQL de upsert.

Ese comportamiento vive en una `DatasetDefinition` registrada en:

```text
registry.py
```

## 3. Componentes principales

## 3.1 `models.py`

Define el lenguaje común que el pipeline entiende.

### `ValidationError`

Todos los validadores deben convertir sus errores a esta estructura:

```python
ValidationError(
    row_number=..., 
    entity_id=..., 
    patient_id=..., 
    field=..., 
    rule=..., 
    message=..., 
    value=...,
)
```

El pipeline no necesita saber si el error provino de un paciente, un encuentro o una observación.

### `ValidationResult`

Contiene:

```text
valid_records
invalid_records
errors
```

### `DatasetPipelineSummary`

Resume una ejecución y expone las rutas de salida.

## 3.2 `registry.py`

Es el punto de extensión de la plataforma.

Cada entrada contiene una `DatasetDefinition`:

```python
DatasetDefinition(
    name="patients",
    columns=(...),
    id_column="patient_id",
    validator=_validate_patients,
    row_builder=_patient_rows,
    upsert_sql=PATIENT_UPSERT_SQL,
)
```

El registro responde cinco preguntas:

1. ¿Cómo se llama el dataset?
2. ¿Qué columnas tiene?
3. ¿Cuál es su identificador?
4. ¿Cómo se valida?
5. ¿Cómo se transforma y persiste?

## 3.3 `pipeline.py`

Expone una única operación:

```python
run_dataset_validation(
    dataset,
    input_path,
    output_directory,
    reference_date=...,
)
```

Su lógica es genérica:

```text
obtener definición
→ leer CSV
→ ejecutar validador registrado
→ escribir válidos
→ escribir inválidos
→ escribir errores
→ escribir quality_report.json
→ devolver resumen
```

No contiene:

```python
if dataset == "patients":
```

Esa ausencia es una señal importante: el pipeline no conoce detalles clínicos específicos.

## 3.4 `database.py`

Expone una única operación:

```python
persist_dataset_validation_outputs(
    connection,
    dataset,
    output_directory,
)
```

Su lógica es:

```text
obtener definición
→ leer quality report
→ verificar conteos
→ convertir registros mediante row_builder
→ insertar pipeline_run
→ ejecutar upsert_sql
→ insertar errores
→ confirmar transacción
```

El módulo no necesita saber qué columnas particulares tiene una observación o un diagnóstico.

## 3.5 Validadores clínicos

Las reglas específicas siguen separadas:

```text
validation.py          → pacientes
clinical_entities.py   → encuentros, diagnósticos y observaciones
```

La arquitectura genérica no significa que todos los datasets tengan las mismas reglas. Significa que todos cumplen la misma interfaz.

## 4. Recorrido de una ejecución

Ejemplo:

```powershell
clinical-data validate-dataset patients data/sample/patients.csv
```

### Paso 1

El CLI recibe `patients`.

### Paso 2

`run_dataset_validation()` consulta:

```python
get_dataset_definition("patients")
```

### Paso 3

El registro devuelve la definición de pacientes.

### Paso 4

El pipeline lee el CSV y ejecuta:

```python
definition.validator(records, reference_date)
```

### Paso 5

El adaptador de pacientes transforma los errores específicos al modelo genérico.

### Paso 6

El pipeline escribe:

```text
valid_patients.csv
invalid_patients.csv
validation_errors.csv
quality_report.json
```

### Paso 7

La carga usa la misma clave `patients` para recuperar:

```text
row_builder
upsert_sql
```

## 5. Por qué se usan adaptadores

Los validadores existentes no tenían exactamente el mismo tipo de error:

```text
ValidationError de pacientes
EntityValidationError de otras entidades
```

En lugar de reescribir inmediatamente todas las reglas clínicas, el registro incluye adaptadores que normalizan sus resultados.

Este patrón permite refactorizar por etapas:

```text
código existente
→ adaptador
→ interfaz común
```

Ventaja: reduce el riesgo de modificar simultáneamente arquitectura y reglas clínicas.

Costo: todavía existe una capa temporal de normalización que puede simplificarse en un refactor posterior.

## 6. Principios aplicados

### Open/Closed Principle

El pipeline está cerrado a modificaciones frecuentes, pero abierto a nuevas definiciones de datasets.

### Dependency Inversion

El pipeline depende de una interfaz y del registro, no de funciones concretas de pacientes.

### Separation of Concerns

- reglas clínicas: validadores;
- configuración: registro;
- flujo: pipeline;
- persistencia: database;
- interfaz: CLI.

### Single Source of Dispatch

La selección del comportamiento se concentra en `DATASET_REGISTRY`, en lugar de distribuirse entre varios `if`.

## 7. Qué debes ser capaz de explicar en una entrevista

### Pregunta: ¿Por qué eliminaste el pipeline especial de pacientes?

Respuesta esperada:

> Porque pacientes y las demás entidades compartían el mismo ciclo de ingestión, validación, generación de outputs y persistencia. Mantener dos implementaciones duplicaba lógica y aumentaba el riesgo de divergencia. Moví las diferencias a un registro de definiciones y dejé un único pipeline invariante.

### Pregunta: ¿Qué es `DatasetDefinition`?

> Es un objeto de configuración ejecutable que agrupa las columnas, el identificador, el validador, la conversión de registros y el SQL de persistencia de un dataset.

### Pregunta: ¿Cómo añadirías medicamentos?

> Implementaría sus reglas, su conversor de filas y su sentencia SQL; después registraría una nueva `DatasetDefinition`. No modificaría `pipeline.py`.

### Pregunta: ¿Cuál es una limitación de este diseño?

> Las definiciones son Python ejecutable, no contratos declarativos. Además, el registro contiene SQL y funciones de conversión, por lo que todavía puede dividirse en contratos, validadores y adaptadores de persistencia más independientes.

## 8. Ejercicios obligatorios

No consideres comprendido el refactor hasta resolver estos ejercicios sin copiar una solución generada.

### Ejercicio 1: dibujar la arquitectura

Dibuja de memoria:

```text
CLI
→ registry
→ pipeline
→ validator
→ outputs
→ database
→ PostgreSQL
```

Explica qué conoce y qué no conoce cada capa.

### Ejercicio 2: rastreo manual

Elige `P006` en `patients.csv` y sigue manualmente:

1. lectura;
2. normalización;
3. regla que falla;
4. error generado;
5. fila de cuarentena;
6. entrada en quality report;
7. entrada en `audit.validation_errors`.

### Ejercicio 3: añadir `labs`

Crea temporalmente:

```text
lab_id,patient_id,test_code,value_numeric,unit,observed_at,source_system
```

Añade el dataset solo mediante:

- validador;
- row builder;
- SQL;
- registro;
- tabla PostgreSQL;
- pruebas.

No modifiques `pipeline.py` ni `database.py`.

### Ejercicio 4: introducir un fallo

Cambia deliberadamente el nombre de un campo en `quality_report.json` y explica por qué la persistencia lo rechaza.

### Ejercicio 5: cambiar una regla

Amplía el rango permitido de frecuencia cardiaca y actualiza su prueba. Explica qué archivos no deben cambiar.

### Ejercicio 6: revisar una decisión

Argumenta a favor y en contra de colocar `upsert_sql` dentro de `DatasetDefinition`.

## 9. Prueba de dominio personal

Puedes afirmar que dominas esta parte cuando seas capaz de:

- explicar el problema original sin leer el código;
- dibujar la arquitectura;
- describir la responsabilidad de cada módulo;
- añadir un dataset pequeño;
- localizar una regla clínica;
- modificar una salida;
- interpretar una prueba fallida;
- justificar una decisión y reconocer sus costos.

## 10. Uso responsable de IA

La IA puede acelerar:

- exploración de alternativas;
- generación inicial de código;
- revisión;
- detección de errores;
- documentación.

No reemplaza:

- comprensión causal;
- juicio de diseño;
- responsabilidad sobre errores;
- capacidad de mantenimiento;
- honestidad sobre la autoría del trabajo.

Una formulación profesional y honesta sería:

> Desarrollé el proyecto usando IA como asistente de ingeniería. Definí el objetivo, revisé la arquitectura, validé los cambios mediante pruebas y estudié cada componente hasta poder explicarlo y modificarlo.

No sería correcto afirmar que escribiste manualmente cada línea. Tampoco sería correcto reducir tu papel a “pagué por el resultado” si realmente comprendes, verificas, decides y mantienes el sistema. La contribución profesional se demuestra por la capacidad de responder por el diseño y evolucionarlo.
