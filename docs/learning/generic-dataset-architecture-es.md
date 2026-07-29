# Guía de estudio: arquitectura genérica de datasets

## Propósito

Esta guía explica el refactor que eliminó el pipeline especial para pacientes. El repositorio ha evolucionado después de ese hito: las reglas que antes se asociaban al registro ahora viven en contratos TOML ejecutables y versionados.

Para estudiar el hito siguiente, consulta:

```text
docs/learning/versioned-executable-contracts-es.md
```

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

Aunque ambos realizaban casi las mismas etapas, estaban implementados en módulos distintos. Esto generaba:

- duplicación;
- tratamiento excepcional de pacientes;
- riesgo de divergencia;
- extensión costosa.

## 2. La decisión arquitectónica

El refactor separó comportamiento invariante y variable.

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

Actualmente se divide en dos categorías.

#### Interfaz y reglas declarativas

```text
contracts/<dataset>/vX.Y.Z.toml
```

Incluyen:

- columnas;
- clave primaria;
- obligatoriedad;
- unicidad;
- tipos;
- categorías;
- reglas temporales;
- perfiles de medición.

#### Persistencia controlada

```text
registry.py
```

Incluye:

- conversión de strings a tipos Python;
- sentencia SQL de upsert.

## 3. Arquitectura actual

```text
CLI
  ↓
Dataset registry
  ↓
Contract manifest
  ↓
Versioned executable contract
  ↓
Generic validation pipeline
  ↓
Quality outputs
  ↓
Generic persistence workflow
  ↓
PostgreSQL
```

No existe:

```python
if dataset == "patients":
```

dentro de `pipeline.py` o `database.py`.

## 4. Componentes principales

### `models.py`

Define el lenguaje común:

```text
ValidationError
ValidationResult
DatasetPipelineSummary
```

### `contract.py`

Carga y ejecuta contratos. Es la fuente de verdad para la interfaz de datos.

### `registry.py`

Mantiene únicamente comportamiento de persistencia que no conviene convertir en configuración libre.

### `pipeline.py`

Expone:

```python
run_dataset_validation(...)
```

Secuencia:

```text
obtener definición
→ cargar contrato activo
→ leer CSV
→ ejecutar contrato
→ escribir válidos
→ escribir inválidos
→ escribir errores
→ escribir quality_report.json
→ devolver resumen
```

### `database.py`

Expone:

```python
persist_dataset_validation_outputs(...)
```

Secuencia:

```text
leer quality report
→ verificar conteos
→ verificar contrato histórico y hash
→ convertir registros mediante row_builder
→ insertar pipeline_run
→ ejecutar upsert_sql
→ insertar errores
→ confirmar transacción
```

## 5. Qué cambió respecto al primer refactor

En la versión `0.3.0`, `DatasetDefinition` contenía:

```text
columns
id_column
validator
row_builder
upsert_sql
```

En la versión `0.4.0`, columnas, clave y reglas se trasladaron al contrato. `DatasetDefinition` conserva:

```text
name
row_builder
upsert_sql
```

Y expone columnas y clave consultando el contrato activo.

Este cambio elimina una segunda fuente de verdad en Python.

## 6. Principios aplicados

### Open/Closed Principle

El pipeline permanece cerrado a modificaciones frecuentes, pero abierto a nuevos datasets mediante contratos y adaptadores.

### Separation of Concerns

```text
contrato        → interfaz y reglas
contract engine → ejecución de reglas
registry        → persistencia específica
pipeline        → orquestación
PostgreSQL      → integridad relacional
CLI             → interacción
```

### Single Source of Truth

La estructura aceptada del dataset vive en el contrato, no simultáneamente en documentación y constantes Python.

### Dependency Inversion

El pipeline depende de modelos y contratos abstractos, no de funciones concretas de pacientes.

## 7. Cómo añadir un dataset

Para añadir `labs` sin modificar `pipeline.py` ni `database.py`:

1. crear `contracts/labs/v1.0.0.toml`;
2. añadirlo al manifest;
3. añadir `DatasetDefinition` con row builder y upsert;
4. crear la tabla o migración;
5. añadir fixtures;
6. añadir pruebas;
7. documentar la interfaz.

La arquitectura no hace que todos los datasets sean iguales. Hace que todos cumplan el mismo ciclo de ejecución.

## 8. Preguntas de entrevista

### ¿Por qué eliminaste el pipeline especial de pacientes?

> Porque pacientes y las demás entidades compartían el mismo ciclo de ingestión, validación, generación de outputs y persistencia. Mantener dos implementaciones duplicaba lógica y aumentaba el riesgo de divergencia.

### ¿Qué función cumple ahora `DatasetDefinition`?

> Asocia el nombre del dataset con su comportamiento de persistencia. La interfaz y las reglas de validación ya no se duplican allí; se obtienen del contrato activo.

### ¿Por qué el pipeline no conoce reglas clínicas?

> Porque su responsabilidad es orquestar. Las reglas cambian por dataset y se describen en contratos ejecutables.

### ¿Cómo añadirías medicamentos?

> Crearía un contrato versionado, el adaptador de persistencia, la tabla o migración y las pruebas. No modificaría el pipeline genérico.

### ¿Cuál es una limitación actual?

> El lenguaje de reglas es deliberadamente limitado y el SQL aún está asociado al registro. Además, faltan migraciones formales, raw storage y estrategia histórica de registros.

## 9. Ejercicios personales

### Ejercicio 1

Dibuja de memoria:

```text
CLI
→ registry
→ manifest
→ contract
→ pipeline
→ outputs
→ database
→ PostgreSQL
```

### Ejercicio 2

Rastrea `P006` desde `patients.csv` hasta `audit.validation_errors`.

### Ejercicio 3

Explica por qué cambiar una regla de presión arterial no requiere editar `pipeline.py`.

### Ejercicio 4

Añade una columna opcional en una nueva versión del contrato de pacientes.

### Ejercicio 5

Argumenta a favor y en contra de mantener `upsert_sql` dentro de `DatasetDefinition`.

## 10. Prueba de dominio personal

Puedes afirmar que dominas esta parte cuando seas capaz de:

- explicar el problema original;
- dibujar la arquitectura actual;
- describir la responsabilidad de cada módulo;
- distinguir contrato y adaptador;
- añadir un dataset pequeño;
- localizar y modificar una regla;
- interpretar una prueba fallida;
- justificar una decisión y reconocer sus costos.

## 11. Uso responsable de IA

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
- honestidad sobre la autoría.

Una formulación profesional y honesta sería:

> Desarrollé el proyecto usando IA como asistente de ingeniería. Definí el objetivo, revisé la arquitectura, validé los cambios mediante pruebas y estudié cada componente hasta poder explicarlo y modificarlo.

La contribución profesional se demuestra por la capacidad de responder por el diseño y evolucionarlo.
