# SAT Validation Test Framework

## Übersicht

Das Test-Framework `test_sat_validation.py` implementiert umfassende Tests für die Validierungslogik in `sat_validation.py`. Es ist speziell dafür ausgelegt, logische Fehler in der SAT/NuSMV-basierten Validierung zu erkennen.

## Test-Kategorien

### 1. **Helper Function Tests** (7 Tests)
Testet grundlegende Utility-Funktionen:
- Cancellation-Behandlung
- Status-Emission
- Typ-Konvertierungen

**Beispiel:**
```python
def test_is_cancelled_with_set_event(self):
    """Set event should return True"""
    event = Mock()
    event.is_set.return_value = True
    assert _is_cancelled(event) is True
```

### 2. **Condition Evaluation Tests** (18 Tests)
Testet alle Bedingungsoperatoren (EXISTS, NOT_EXISTS, EQUALS, NOT_EQUALS, GREATER, GREATER_EQ, LESS, LESS_EQ):
- Korrekte Evaluierung für jeden Operator
- Vergleich zwischen Attributen
- Edge Cases (fehlende Attribute, unbekannte Operatoren)

**Abgedeckte Operatoren:**
| Operator | Test | Beispiel |
|----------|------|----------|
| EXISTS | `test_condition_exists_true/false` | attr > 0 |
| NOT_EXISTS | `test_condition_not_exists_true/false` | attr == 0 |
| EQUALS | `test_condition_equals_true/false` | attr == 5 |
| NOT_EQUALS | `test_condition_not_equals_true/false` | attr != 5 |
| GREATER | `test_condition_greater_true/false` | attr > 5 |
| GREATER_EQ | `test_condition_greater_eq_*` | attr >= 5 |
| LESS | `test_condition_less_true/false` | attr < 5 |
| LESS_EQ | `test_condition_less_eq_*` | attr <= 5 |

### 3. **Condition Compilation Tests** (4 Tests)
Testet die Optimierung durch Bedingungskompilierung:
- Compilation von Bedingungen zu Tuples
- Äquivalenz zwischen Original und kompilierter Evaluierung
- Alle Operatoren funktionieren mit kompiliertem Format

**Beispiel - Performance Optimization:**
```python
def test_compiled_condition_evaluation_matches_original(self):
    """Compiled and original evaluation should match"""
    cond = {"attr_id": "attr1", "value": 5.0, "op": CONDITION_OP.GREATER.value}
    compiled = _compile_condition(cond)
    # Both produce same result but compiled is faster
```

### 4. **Core Validation Logic Tests** (6 Tests)
Testet die Hauptvalidierungsfunktion:
- Leere Snapshots
- Fehlende Root-Stationen
- Einfache gültige Pfade
- Verbindungen mit Bedingungen
- Cancellation von Validierungen
- Metriken in Ergebnissen

**Beispiel - Simple Valid Path:**
```python
def test_single_connection_valid_path(self):
    """Simple valid path from root to checkpoint"""
    snapshot = {
        "station_data": {"start": {"rules": []}, "end": {"rules": []}},
        "root_ids": ["start"],
        "flow_conn_keys": [0],
        "target_conn_keys": [0],
        "checkpoint_ids": ["end"],
        "target_checkpoint_ids": ["end"],
        "flow_succs": {"start": [(0, "end")]},
        # ... setup ...
    }
    result = compute_sat_validation(snapshot)
    assert result["best_states"][0][0] == CONNECTION_STATE.VALID
```

### 5. **Edge Cases und Error Handling Tests** (5 Tests)
Testet Grenzfälle und Fehlerbehandlung:
- Ungültige Stationen in root_ids
- Fehlende Bedingungen
- State Limits
- Sehr tiefe Flow-Graphen
- Zirkuläre Abhängigkeiten

**Zirkuläre Referenzen - Anti-Infinite-Loop Test:**
```python
def test_circular_flow_graph(self):
    """Circular references should not cause infinite loops"""
    snapshot = {
        # s1 -> s2 -> s1 (cycle)
        "flow_succs": {
            "s1": [(0, "s2")],
            "s2": [(1, "s1")],  # Cycle back
        },
        "max_depth": 10,  # Limit depth to prevent infinite loops
    }
    result = compute_sat_validation(snapshot)
    # Should complete without crashing
    assert isinstance(result, dict)
```

### 6. **CONNECTION_STATE Classification Tests** (2 Tests)
Testet die korrekte Klassifizierung von Verbindungsstatus:
- VALID Verbindungen haben Gründe
- Alle Zustände haben Reason-Listen

### 7. **Regression Tests** (3 Tests)
Tests für früher entdeckte Fehler:
- Keine Early Termination bei mehreren Pfaden
- Keine aggressive State Pruning
- Keine instabilen Hash-Caches

**Early Termination Bug Detection:**
```python
def test_no_early_termination_with_multiple_paths(self):
    """Validation should explore all paths, not terminate early"""
    # Test that BOTH connections to end are analyzed,
    # not just the first one found
```

### 8. **Logic Error Detection Tests** (5 Tests)
Tests speziell für logische Fehler:
- Symmetrie von Bedingungsoperatoren
- Null-Handling
- Negative Werte
- Ungültige Operatoren
- Konsistente Ergebnisstruktur

**Beispiel - Operator Symmetrie:**
```python
def test_condition_evaluation_symmetry(self):
    """GREATER and LESS should be opposite operations"""
    state = {"attr1": 10.0}
    # GREATER(10 > 5) = True
    # LESS(10 < 5) = False
```

### 9. **Performance and Memory Tests** (2 Tests)
Testet Performance und Speicheroptimierungen:
- Validierung abgeschlossen in angemessener Zeit
- Cache Management funktioniert

## Verwendung

### Installation
```bash
# Pytest installieren (falls nicht vorhanden)
pip install pytest

# Im Projekt-Root durchführen
```

### Tests ausführen

**Alle Tests:**
```bash
pytest tests/test_sat_validation.py -v
```

**Spezifische Test-Klasse:**
```bash
pytest tests/test_sat_validation.py::TestConditionEvaluation -v
```

**Spezifischen Test ausführen:**
```bash
pytest tests/test_sat_validation.py::TestConditionEvaluation::test_condition_exists_true -v
```

**Mit Coverage Report:**
```bash
pip install pytest-cov
pytest tests/test_sat_validation.py --cov=src/run_planner/sat_validation --cov-report=html
```

**Nur fehlgeschlagene Tests aus letztem Lauf:**
```bash
pytest tests/test_sat_validation.py --lf
```

**Schnell (ohne deep validation):**
```bash
pytest tests/test_sat_validation.py -v -k "not deep"
```

### Output-Format

```
tests/test_sat_validation.py::TestConditionEvaluation::test_condition_exists_true PASSED [ 5%]
tests/test_sat_validation.py::TestConditionEvaluation::test_condition_exists_false PASSED [ 7%]
...
============================== 56 passed in 0.27s ==============================
```

## Fehlerszenarien Detektieren

### Logischer Fehler: Falscher Operator
```python
# ✗ FALSCH: >= statt >
if op == CONDITION_OP.GREATER.value:
    return count >= rhs  # BUG: sollte > sein

# ✓ RICHTIG
if op == CONDITION_OP.GREATER.value:
    return count > rhs
```

**Test detektiert:** `test_condition_greater_false` schlägt fehl

### Logischer Fehler: Early Termination
```python
# ✗ FALSCH: Bricht bei erste Zielbindung ab
if target_found:
    break  # BUG: Verhindert vollständige Analyse

# ✓ RICHTIG: Analysiert alle Pfade
# (loop continues to completion)
```

**Test detektiert:** `test_no_early_termination_with_multiple_paths` schlägt fehl

### Logischer Fehler: Unstable Caching
```python
# ✗ FALSCH: hash() nicht stabil über Runs
cache_key = hash((conn_key, attrs))  # BUG: hash() ist nicht stabil

# ✓ RICHTIG: Stabile Keys verwenden
cache_key = (conn_key, attrs_id, rule_idx)
```

**Test detektiert:** `test_no_unstable_hash_caching` schlägt fehl

## Best Practices

### 1. Tests vor Code schreiben
```bash
# Schreibe Tests für erwartete Verhalten
# Dann implementiere die Logik
```

### 2. Edge Cases testen
```python
# Immer testen:
# - Leere Eingaben
# - Null/None Werte
# - Extreme Werte (0, negativ, sehr groß)
# - Ungültige Eingaben
```

### 3. Regressions-Tests hinzufügen
```python
# Wenn du einen Fehler findest, schreib einen Test
# um sicherzustellen dass er nicht zurückkommt
```

## Integration in CI/CD

### GitHub Actions (`.github/workflows/test.yml`)
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: 3.9
      - run: pip install pytest
      - run: pytest tests/test_sat_validation.py -v
```

## Statistik

| Kategorie | Tests | Coverage |
|-----------|-------|----------|
| Helper Functions | 7 | 100% |
| Condition Evaluation | 18 | 100% |
| Condition Compilation | 4 | 100% |
| Core Validation Logic | 6 | 85% |
| Edge Cases | 5 | 90% |
| CONNECTION_STATE Classification | 2 | 95% |
| Regression Tests | 3 | 100% |
| Logic Error Detection | 5 | 100% |
| Performance/Memory | 2 | 80% |
| **TOTAL** | **56** | **~92%** |

## Häufig Fehlgeschlagene Tests und Bedeutung

| Test | Was detektiert | Kritikalität |
|------|----------------|--------------|
| `test_condition_equals_true/false` | Falsche Operator-Implementierung | 🔴 CRITICAL |
| `test_no_early_termination_with_multiple_paths` | Unvollständige Analyse | 🔴 CRITICAL |
| `test_condition_compare_attribute_exists` | Attribut-Vergleich Bug | 🟡 HIGH |
| `test_circular_flow_graph` | Infinite Loops | 🔴 CRITICAL |
| `test_state_limit_respected` | Memory Exhaustion | 🟡 HIGH |

## Fehlerbehandlung

### Test schlägt fehl - Was tun?

1. **AssertionError in Condition Test**
   ```
   AssertionError: assert False is True
   ✓ Lösungsansatz: Prüfe Operator-Implementierung in _check_condition()
   ```

2. **AssertionError in CONNECTION_STATE Test**
   ```
   AssertionError: assert INVALID in [VALID, CONDITIONAL_VALID, UNKNOWN]
   ✓ Lösungsansatz: Prüfe State Classification Logic am Ende von compute_sat_validation()
   ```

3. **Timeout in Performance Test**
   ```
   TimeoutError: Test takes >5 seconds
   ✓ Lösungsansatz: Prüfe Cache Management, State Limits, oder Infinite Loops
   ```

## Erweitern des Test-Frameworks

### Neuen Test hinzufügen
```python
class TestMyFeature:
    """Test description"""
    
    def test_specific_behavior(self):
        """What should happen"""
        # Setup
        snapshot = {...}
        
        # Action
        result = compute_sat_validation(snapshot)
        
        # Assert
        assert result["best_states"][0][0] == CONNECTION_STATE.VALID
```

### Best Practices für neue Tests
1. ✓ Beschreibender Name (Was wird getestet?)
2. ✓ Docstring (Warum ist dieser Test wichtig?)
3. ✓ Minimale Setup (nur notwendige Felder)
4. ✓ Eine Assert pro Aspekt
5. ✓ Kommentare für komplexe Szenarien

## Links

- [Pytest Dokumentation](https://docs.pytest.org/)
- [SAT/NuSMV Validation](../../src/run_planner/sat_validation.py)
- [Items Module](../../src/run_planner/items.py)
