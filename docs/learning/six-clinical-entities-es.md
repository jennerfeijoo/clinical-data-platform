# Guía de estudio: seis entidades clínicas

## Objetivo

Este hito completa el modelo clínico mínimo del repositorio mediante dos entidades nuevas:

- `medications`;
- `procedures`.

No se añadió un pipeline paralelo. Ambas entidades utilizan la misma secuencia genérica que pacientes, encuentros, diagnósticos y observaciones.

```text
CSV externo
→ captura raw
→ contrato activo
→ validación genérica
→ outputs de calidad
→ migraciones
→ verificación de lineage
→ persistencia genérica
→ PostgreSQL
```

## 1. Por qué seis entidades

Las seis entidades cubren un recorrido clínico básico:

```text
Paciente
→ tiene encuentros
→ durante esos encuentros recibe diagnósticos
→ se registran observaciones
→ se administran o prescriben medicamentos
→ se realizan procedimientos
```

Esto no pretende reproducir un EHR completo. El objetivo es demostrar que la arquitectura puede extenderse a entidades heterogéneas sin duplicar el pipeline.

## 2. Qué cambió para añadir un dataset

Para cada nueva entidad se añadieron cinco componentes.

### Contrato ejecutable

```text
contracts/medications/v1.0.0.toml
contracts/procedures/v1.0.0.toml
```

Declaran columnas, tipos, obligatoriedad, vocabularios y reglas temporales.

### Manifest

`manifest.toml` activa explícitamente ambos contratos.

### Adaptador del registro

`registry.py` convierte strings validados en tipos PostgreSQL y define el SQL de persistencia.

### Migración

V006 crea tablas, constraints, funciones de hash, triggers e índices.

### Datos y pruebas

Se añadieron fixtures sintéticos, pruebas de contratos, migraciones, persistencia, duplicados, conflictos y flujo end-to-end.

## 3. Medication como evento

Una fila de medicamento representa un evento identificado por `medication_id`.

Campos principales:

```text
medication_id
patient_id
encounter_id
code_system
medication_code
status
start_datetime
end_datetime
dose_value
dose_unit
route
source_system
```

### Campos opcionales

`end_datetime`, `dose_value`, `dose_unit` y `route` pueden estar vacíos según el contrato.

El adaptador convierte:

```text
"" → None
"500" → 500.0
fecha ISO → datetime
```

### Reglas divididas por capa

El contrato verifica:

- campos obligatorios;
- tipos;
- código de sistema permitido;
- estado permitido;
- ruta permitida cuando existe;
- `start_datetime <= end_datetime`.

PostgreSQL verifica además:

- paciente existente;
- encuentro existente;
- dosis positiva;
- dosis y unidad presentes juntas;
- identidad inmutable.

Esta separación evita convertir el contrato de archivo en un sustituto de la integridad relacional.

## 4. Procedure como evento

Una fila de procedimiento representa un evento identificado por `procedure_id`.

Campos:

```text
procedure_id
patient_id
encounter_id
code_system
procedure_code
procedure_datetime
status
source_system
```

El contrato admite actualmente los nombres de sistemas `SNOMED`, `CPT` e `ICD10PCS`. Esto solo valida la declaración del sistema, no comprueba que el código exista en una versión oficial.

## 5. Inmutabilidad

Medicamentos y procedimientos siguen la misma política que encuentros, diagnósticos y observaciones.

### Duplicado exacto

```text
mismo ID
+ mismo contenido clínico normalizado
→ no-op
→ conservar evento y lineage originales
```

### Conflicto

```text
mismo ID
+ contenido clínico diferente
→ error de integridad
→ rollback completo
```

Esto evita que una segunda carga cambie silenciosamente un evento ya aceptado.

## 6. Record hash

V006 crea:

```text
clinical.medication_record_sha256(...)
clinical.procedure_record_sha256(...)
```

El hash incluye contenido clínico normalizado y excluye:

```text
source_run_id
source_sha256
loaded_at
```

Por eso una recepción idéntica no se interpreta como un cambio clínico.

## 7. Orden de carga

El orden del manifest y del registro importa porque existen claves foráneas.

```text
patients
→ encounters
→ diagnoses
→ observations
→ medications
→ procedures
```

Medicamentos y procedimientos requieren que sus pacientes y encuentros ya existan.

## 8. Preguntas que debes poder responder

1. ¿Por qué medications y procedures no requieren cambios en `pipeline.py`?
2. ¿Qué parte del sistema decide las columnas aceptadas?
3. ¿Qué parte convierte fechas y números?
4. ¿Qué parte crea las tablas?
5. ¿Por qué un contrato válido puede fallar en PostgreSQL?
6. ¿Por qué `record_sha256` no incluye `source_run_id`?
7. ¿Qué diferencia hay entre un duplicado exacto y un conflicto de identidad?
8. ¿Por qué `code_system` no equivale todavía a normalización terminológica?

## 9. Recorrido de un medicamento

Sigue `M002`:

```text
medications.csv
→ raw receipt
→ medications/v1.0.0.toml
→ valid_medications.csv
→ _medication_rows()
→ MEDICATION_UPSERT_SQL
→ trg_medications_immutable
→ clinical.medications
```

Debes identificar en qué etapa:

- la fecha se convierte a `datetime`;
- el end vacío se convierte a `None`;
- la dosis se convierte a `float`;
- se calcula `record_sha256`;
- se comprueban las claves foráneas.

## 10. Ejercicios

### Ejercicio 1: nueva ruta

Añade temporalmente `INTRAMUSCULAR` al contrato de medicamentos.

Determina qué más debe cambiar para mantener coherencia entre contrato y PostgreSQL.

### Ejercicio 2: dosis inconsistente

Crea una fila con:

```text
dose_value = 10
dose_unit = vacío
```

Explica por qué puede superar las reglas actuales del contrato pero debe fallar en PostgreSQL.

### Ejercicio 3: evento conflictivo

Carga `M001` y luego vuelve a usar `M001` con estado `STOPPED`.

Verifica:

- el error de integridad;
- el rollback de `audit.pipeline_runs`;
- la conservación del evento original.

### Ejercicio 4: relación inexistente

Crea un procedimiento con `encounter_id = E999`.

Explica la diferencia entre validez intrínseca de la fila e integridad relacional.

### Ejercicio 5: séptima entidad

Diseña `allergies` sin modificar `pipeline.py` ni `database.py`.

Enumera los componentes necesarios:

```text
contrato
manifest
sample
row builder
SQL de persistencia
migración
política histórica
pruebas
documentación
```

## 11. Explicación profesional

> La plataforma modela seis entidades clínicas. Las dos nuevas entidades, medicamentos y procedimientos, se incorporaron mediante contratos versionados, adaptadores del registro y una migración, sin crear pipelines especiales. Ambas se tratan como eventos inmutables: duplicados exactos preservan el registro original y la reutilización conflictiva del identificador revierte la transacción. Las claves foráneas relacionan los eventos con pacientes y encuentros, mientras que hashes de contenido normalizado separan identidad clínica de lineage de carga.

## 12. Límite actual

El repositorio todavía no realiza normalización terminológica real. Los contratos controlan valores de `code_system`, pero no verifican códigos contra versiones oficiales, tablas de referencia, relaciones jerárquicas o mapeos entre sistemas. Ese es el siguiente hito.
