# Reportes de attrition y missingness

## 1. Qué añade este hito

La plataforma ya podía generar, adaptar, comparar y cargar dos cohortes sintéticas independientes. El siguiente problema era explicar qué ocurrió con los datos durante la transformación:

```text
¿Cuántas filas entraron?
¿Cuántas se conservaron?
¿Cuántas se omitieron?
¿Por qué se omitieron?
¿Qué campos llegan vacíos?
¿Esas ausencias violan el contrato o son esperadas?
¿Las dos cohortes muestran patrones diferentes?
```

Este hito convierte esas preguntas en artefactos reproducibles.

## 2. Attrition no significa abandono de pacientes aquí

En estudios clínicos, attrition puede referirse a participantes que abandonan el seguimiento. Ese no es el significado utilizado en este módulo.

Aquí significa:

> pérdida técnica de filas entre un archivo fuente de Synthea y el dataset interno adaptado.

Ejemplo:

```text
observations.csv: 4 filas fuente
→ 3 observaciones compatibles con el contrato
→ 1 observación fuera del subconjunto soportado
```

Por tanto:

```text
source_rows = adapted_rows + omitted_rows
```

La plataforma detiene el reporte si esa igualdad no se cumple.

## 3. De dónde salen las razones de exclusión

El adaptador ya registra razones explícitas, por ejemplo:

```text
observation_outside_supported_subset
encounter_invalid_datetime
condition_invalid_parent
medication_missing_code
procedure_unsupported_code
```

El reporte asigna cada razón a una entidad mediante prefijos controlados:

| Dataset | Prefijo |
|---|---|
| patients | `patient_` |
| encounters | `encounter_` |
| diagnoses | `condition_` |
| observations | `observation_` |
| medications | `medication_` |
| procedures | `procedure_` |

Una razón desconocida no se ignora. Produce un error para evitar que la attrition quede subestimada.

## 4. Tasas utilizadas

Para cada dataset:

```text
retention_rate = adapted_rows / source_rows
attrition_rate = omitted_rows / source_rows
```

Cuando el archivo fuente contiene cero filas, el denominador no existe. En ese caso el JSON usa `null` y el CSV deja la tasa vacía. No se inventa una tasa de cero.

## 5. Qué significa missingness

El reporte considera missing un valor que queda vacío después de eliminar espacios.

```text
""       → missing
"   "    → missing
"0"      → presente
"UNKNOWN"→ presente
"NA"     → presente
```

La plataforma no interpreta automáticamente `NA` o `UNKNOWN` como nulos porque eso requeriría una política explícita del sistema fuente.

## 6. Dos capas de missingness

### 6.1 Missingness de fuente

Se analiza cada columna de los seis CSV originales de Synthea.

Este análisis es descriptivo. No afirma que una columna fuente sea obligatoria o clínicamente necesaria.

### 6.2 Missingness adaptada

Se analiza cada campo de los seis datasets internos. Aquí sí existe un contrato ejecutable que indica si el campo es requerido.

## 7. Clasificación contract-aware

### Required

El contrato exige un valor.

```text
required = true
```

Una ausencia sería un error. Como el reporte verifica primero el manifiesto y los contratos, el resultado esperado es:

```text
required_missing_cells = 0
```

### Optional

El contrato permite la ausencia.

Ejemplos:

```text
patients.death_date
medications.end_datetime
```

Un paciente vivo puede no tener `death_date`. Un medicamento activo puede no tener `end_datetime`. La ausencia no implica automáticamente mala calidad.

### Structural

El adaptador actual no recibe un valor estructurado fiable para ese campo.

```text
medications.dose_value
medications.dose_unit
medications.route
```

Synthea exporta un código y una descripción del medicamento, pero el CSV utilizado no proporciona esos tres componentes de forma suficientemente estructurada para este contrato. Por eso se conservan vacíos y se clasifican como missingness estructural.

## 8. Completitud por fila

El reporte calcula:

```text
rows_complete_all_fields
rows_with_any_missing
rows_missing_required
```

Una fila puede estar incompleta en sentido literal y seguir siendo válida.

Ejemplo:

```text
patient_id     presente
birth_date     presente
sex_at_birth   presente
death_date     vacío
source_system  presente
```

La fila no está completa en todos los campos, pero sí está completa en todos los campos requeridos.

## 9. Completitud por celda

También se cuentan:

```text
adapted_total_cells
adapted_missing_cells
required_missing_cells
structural_missing_cells
```

La tasa de missingness por celda es:

```text
adapted_missing_cells / adapted_total_cells
```

Esta tasa debe interpretarse con cuidado porque combina campos con significados diferentes.

## 10. Artefactos generados

```text
data/synthea/cohort-quality/
├── synthea-quality-report.json
├── synthea-quality-report.md
├── attrition.csv
├── attrition-reasons.csv
├── source-missingness.csv
├── adapted-missingness.csv
├── row-completeness.csv
├── cohort-quality-comparison.csv
└── cohort-comparison/
```

### JSON

Contiene toda la evidencia estructurada y el fingerprint del reporte.

### Markdown

Resume los resultados para revisión humana.

### CSV

Permiten análisis posterior con R, Python, SQL, Excel o herramientas de visualización.

## 11. Comparación A frente a B

El archivo `cohort-quality-comparison.csv` compara por entidad:

```text
filas fuente
filas adaptadas
retention rate
missing-cell rate
```

Las diferencias se calculan como:

```text
cohort_b - cohort_a
```

Son diferencias descriptivas. No se ejecutan pruebas de hipótesis, intervalos de confianza ni inferencia clínica.

## 12. Fingerprint reproducible

El fingerprint incluye:

```text
versión del esquema del reporte
fingerprint de comparación de cohortes
hashes de los perfiles
fingerprints de adaptación
contratos y hashes de contratos
conteos de attrition
razones de omisión
conteos de missingness
completitud por fila y celda
comparación descriptiva
```

No incluye:

```text
created_at
ruta absoluta de salida
```

Repetir el reporte sobre los mismos archivos produce el mismo fingerprint aunque cambien la fecha de ejecución o la carpeta de salida.

## 13. Ejecución

Después de generar las dos cohortes:

```powershell
.\scripts\generate_synthea_cohorts.ps1
```

Generar el reporte:

```powershell
.\scripts\report_synthea_quality.ps1
```

Reemplazar un reporte anterior:

```powershell
.\scripts\report_synthea_quality.ps1 -Replace
```

Comando directo:

```powershell
clinical-data-cohort quality-report `
  data/synthea/synthea-us-small-v1/normalized `
  data/synthea/synthea-us-small-cohort-b-v1/normalized `
  --output-dir data/synthea/cohort-quality
```

## 14. Qué protege el sistema

El reporte rechaza:

```text
archivos fuente alterados
archivos adaptados alterados
perfiles incompatibles
identificadores solapados entre cohortes
etiquetas de ruta inseguras
razones de omisión desconocidas
conteos negativos
attrition que no reconcilia
required missingness distinta de cero
sobrescritura accidental
```

## 15. Cómo leer un resultado

Suponga este resultado:

| Dataset | Fuente | Adaptado | Omitido | Retención |
|---|---:|---:|---:|---:|
| observations | 4 | 3 | 1 | 75% |

Y esta razón:

```text
observation_outside_supported_subset = 1
```

La interpretación correcta es:

> El adaptador conservó tres de cuatro filas porque el contrato interno soporta únicamente presión sistólica, presión diastólica y frecuencia cardiaca. La cuarta observación se excluyó de forma explícita y auditable.

La interpretación incorrecta sería:

> La cohorte perdió al 25% de los pacientes.

Las unidades son filas de observaciones, no pacientes.

## 16. Ejercicios

### Ejercicio 1

Revise `attrition.csv` y compruebe para cada fila:

```text
source_rows = adapted_rows + omitted_rows
```

### Ejercicio 2

Busque campos con:

```text
classification = structural
```

Explique por qué 100% de missingness no representa necesariamente un error.

### Ejercicio 3

Busque:

```text
required = True
missing_count > 0
```

El resultado esperado es ningún registro.

### Ejercicio 4

Cambie el fixture para añadir una observación LOINC no soportada, regenere la adaptación y prediga qué cambiará:

```text
source_rows de observations      aumenta
adapted_rows                     permanece
omitted_rows                     aumenta
attrition_rate                   aumenta
quality_fingerprint              cambia
```

### Ejercicio 5

Mueva las carpetas adaptadas sin modificar su contenido. El fingerprint de calidad debe permanecer estable siempre que los manifiestos sigan pudiendo resolver los archivos fuente verificados.

## 17. Límites

Este reporte no demuestra:

- calidad de datos de un hospital real;
- representatividad epidemiológica;
- ausencia clínica real;
- mecanismos MCAR, MAR o MNAR;
- pérdida de seguimiento de pacientes;
- validez estadística de diferencias entre cohortes;
- preparación para PHI.

Demuestra que la plataforma puede cuantificar y explicar de manera reproducible qué datos sintéticos entran, cuáles se conservan, cuáles se excluyen y dónde permanecen valores vacíos bajo contratos explícitos.
