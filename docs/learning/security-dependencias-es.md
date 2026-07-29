# Seguridad automatizada y auditoría de dependencias

## 1. Qué problema resuelve este hito

Las pruebas funcionales pueden confirmar que el software hace lo esperado, pero no responden por sí solas a preguntas como:

```text
¿Una dependencia instalada tiene una vulnerabilidad conocida?
¿El código contiene un patrón inseguro?
¿La imagen Docker contiene bibliotecas vulnerables?
¿Las acciones de GitHub pueden cambiar sin revisión?
```

La versión `0.19.0` incorpora controles separados para estas superficies.

## 2. Modelo de defensa en capas

```text
entorno Python resuelto
→ pip-audit
→ SBOM CycloneDX

src/
→ Bandit + baseline revisada
→ CodeQL

Dockerfile
→ build de imagen
→ Trivy

workflows
→ acciones fijadas por SHA

versiones futuras
→ Dependabot
```

Ningún escáner sustituye a los demás. Cada uno observa una parte distinta del sistema.

## 3. `pip-audit`

`pip-audit` compara las versiones instaladas con bases de vulnerabilidades conocidas.

La ejecución utilizada es:

```bash
python -m pip_audit --local
```

El job se ejecuta en cada pull request. Si una dependencia añadida hace que el entorno propuesto contenga una vulnerabilidad conocida, el pull request falla.

No es una comparación exacta entre base y head: audita todo el entorno resuelto del head. Esto permite bloquear vulnerabilidades, pero no identifica por sí solo qué commit introdujo cada una.

Además se genera un SBOM CycloneDX:

```text
python-sbom.cdx.json
```

El SBOM es un inventario de componentes del entorno resuelto. No es una prueba de seguridad y tampoco reemplaza un lockfile.

## 4. Primer hallazgo real: `setuptools`

La primera ejecución detectó:

```text
setuptools 79.0.1
→ vulnerabilidad conocida
→ versión corregida: 83.0.0
```

La solución no fue ignorar el aviso. Se elevó el mínimo de construcción:

```toml
[build-system]
requires = ["setuptools>=83"]
```

y el workflow actualiza `setuptools` antes de auditar.

Este ejemplo muestra el valor del control: una dependencia de construcción también forma parte de la superficie de supply chain.

## 5. Bandit

Bandit analiza el código Python buscando patrones potencialmente inseguros.

La política exige:

```text
severidad mínima: media
confianza mínima: media
```

Comando:

```bash
python -m bandit -r src -ll -ii \
  -b security/bandit-baseline.json
```

## 6. Baseline revisada de Bandit

La primera ejecución detectó dos B608 relacionados con composición de SQL mediante strings.

### Caso 1: bloqueo de una ejecución

El código añade:

```text
""
o
" FOR UPDATE"
```

según un booleano interno. El `run_id` continúa parametrizado.

### Caso 2: preflight de dos cohortes

Los nombres de tabla y columna se obtienen exclusivamente del registro constante:

```text
patients      → patient_id
encounters    → encounter_id
diagnoses     → diagnosis_id
observations  → observation_id
medications   → medication_id
procedures    → procedure_id
```

Los identificadores clínicos continúan parametrizados.

Estos dos hallazgos se conservaron en:

```text
security/bandit-baseline.json
```

No se desactivó B608 globalmente. Una prueba exige que la baseline contenga exactamente dos resultados, en esos dos archivos, con el test B608 y severidad media. Un tercer hallazgo o un cambio de ubicación vuelve a bloquear el workflow.

## 7. CodeQL

CodeQL representa el código como datos consultables y aplica consultas de seguridad sobre flujos y relaciones del programa.

En el repositorio se utiliza:

```text
lenguaje: Python
query suite: security-extended
```

Bandit y CodeQL no son redundantes. Bandit se orienta principalmente a patrones locales; CodeQL puede estudiar relaciones y propagaciones más amplias.

## 8. Por qué no se usa Dependency Review Action

La primera implementación intentó ejecutar GitHub Dependency Review. GitHub la rechazó porque Dependency Graph no está habilitado en este repositorio.

No se ocultó el error con `continue-on-error`. La acción incompatible se retiró y se mantuvo como gate el análisis completo del entorno mediante `pip-audit`.

La diferencia es importante:

```text
Dependency Review
→ compara cambios entre base y pull request

pip-audit del head
→ evalúa todo el entorno propuesto
```

La implementación actual ofrece la segunda garantía, no la primera.

## 9. Trivy y la imagen Docker

Trivy analiza:

```text
paquetes del sistema operativo
bibliotecas del lenguaje
```

Se bloquean vulnerabilidades:

```text
HIGH
CRITICAL
```

La primera ejecución encontró versiones corregibles de:

```text
jaraco.context 5.3.0 → mínimo 6.1.0
wheel 0.45.1         → mínimo 0.46.2
```

El Dockerfile ahora actualiza:

```text
setuptools >=83
wheel >=0.46.2
jaraco.context >=6.1.0
```

La política ignora como condición de fallo los hallazgos sin corrección disponible. Siguen siendo visibles. “Sin corrección” no significa “sin riesgo”; significa que el pipeline no dispone de una versión reparada que instalar.

## 10. Dependabot

Dependabot revisa semanalmente:

```text
pip
GitHub Actions
Docker
```

Dependabot no fusiona automáticamente. Abre pull requests que deben pasar revisión, CI, benchmark y security scanning.

## 11. Acciones fijadas por SHA

Una referencia mutable como:

```yaml
uses: actions/checkout@v4
```

puede apuntar a contenido diferente en el futuro.

La plataforma utiliza:

```yaml
uses: actions/checkout@<SHA completo> # versión legible
```

El SHA fija el contenido exacto ejecutado. Una prueba recorre todos los workflows y rechaza referencias que no utilicen 40 caracteres hexadecimales.

## 12. Por qué existe una ejecución programada

Una dependencia puede pasar hoy y aparecer mañana en una nueva alerta, aunque el repositorio no cambie.

Por eso el workflow se ejecuta:

```text
cada pull request
cada push a main
manualmente
semanalmente
```

## 13. Evidencia generada

Los jobs publican:

```text
pip-audit.json
python-sbom.cdx.json
bandit.json
```

CodeQL y Trivy mantienen sus resultados asociados a la ejecución de GitHub Actions.

## 14. Ejecución local

```powershell
python -m pip install --upgrade pip "setuptools>=83"
python -m pip install -e ".[dev,security]"
python -m pip check
python -m pip_audit --local --progress-spinner off
python -m bandit -r src -ll -ii -b security/bandit-baseline.json
```

La ejecución local puede diferir de CI porque las versiones transitivas y el sistema operativo pueden ser distintos.

## 15. Preguntas que debes poder responder

1. ¿Qué diferencia existe entre una prueba funcional y un escáner de vulnerabilidades?
2. ¿Qué analiza `pip-audit` y qué no analiza?
3. ¿Por qué un SBOM no es un lockfile?
4. ¿Por qué se actualizó `setuptools` aunque no sea una dependencia clínica?
5. ¿Qué significan severidad y confianza en Bandit?
6. ¿Por qué una baseline es preferible a desactivar B608 globalmente?
7. ¿Qué diferencia existe entre Dependency Review y el audit del entorno head?
8. ¿Qué componentes inspecciona Trivy?
9. ¿Por qué se fijan las acciones mediante SHA completo?
10. ¿Por qué un workflow verde no demuestra seguridad total?

## 16. Explicación profesional defendible

> La plataforma aplica controles de seguridad en varias capas. `pip-audit` examina el entorno Python completo de cada pull request y genera un SBOM CycloneDX. Bandit ejecuta un gate de severidad y confianza medias contra una baseline limitada a dos consultas construidas exclusivamente con constantes internas. CodeQL añade análisis de flujos. Trivy inspecciona la imagen y bloquea vulnerabilidades altas o críticas con corrección disponible. Dependabot propone actualizaciones y todas las acciones externas están fijadas mediante SHA completo. La Dependency Review Action no se presenta como implementada porque el Dependency Graph del repositorio no está habilitado.

## 17. Límites

Este hito no demuestra:

```text
ausencia de vulnerabilidades desconocidas
seguridad de despliegue
cumplimiento regulatorio
preparación para PHI
resistencia completa a ataques de supply chain
seguridad clínica
```

El repositorio continúa limitado a datos sintéticos y aprendizaje de ingeniería.
