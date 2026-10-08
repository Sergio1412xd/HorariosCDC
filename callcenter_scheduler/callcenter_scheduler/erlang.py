"""
erlang.py
Motor de cálculo de dimensionamiento de personal para call center.
Basado en el modelo Erlang C (estándar de la industria).

Conceptos clave:
- A (intensidad de tráfico, en Erlangs): cuánto "trabajo" llega en el intervalo.
      A = (llamadas * TMO_segundos) / duracion_intervalo_segundos
- N (agentes): cuántos asesores atienden simultáneamente.
- Pw (Erlang C): probabilidad de que una llamada tenga que esperar (todos ocupados).
- Nivel de Servicio (SL): % de llamadas contestadas dentro de un tiempo objetivo
  (ej. "80% de las llamadas contestadas en 20 segundos").
- Ocupación: % del tiempo que el agente está en llamada (si es muy alta -> se queman,
  si es muy baja -> estás sobre-dimensionado / caro).
"""

import math
from dataclasses import dataclass


def _erlang_b(A: float, N: int) -> float:
    """
    Erlang B recursivo (numéricamente estable, sin factoriales que desborden).
    B(0) = 1
    B(n) = (A * B(n-1)) / (n + A * B(n-1))
    """
    b = 1.0
    for n in range(1, N + 1):
        b = (A * b) / (n + A * b)
    return b


def erlang_c_prob_wait(A: float, N: int) -> float:
    """
    Probabilidad de que una llamada entrante tenga que esperar (todos los N agentes ocupados).
    Derivada de Erlang B (estable para cualquier volumen de llamadas).
    A = intensidad de tráfico en Erlangs
    N = número de agentes
    """
    if N <= A:
        # Sistema inestable: la cola crece infinitamente. No hay suficientes agentes.
        return 1.0

    eb = _erlang_b(A, N)
    pw = eb / (1 - (A / N) * (1 - eb))
    return pw


def service_level(A: float, N: int, aht_seconds: float, target_seconds: float) -> float:
    """
    % de llamadas contestadas dentro de 'target_seconds' (ej. 20 segundos).
    """
    if N <= A:
        return 0.0

    pw = erlang_c_prob_wait(A, N)
    sl = 1 - pw * math.exp(-(N - A) * (target_seconds / aht_seconds))
    return max(0.0, min(1.0, sl))


def occupancy(A: float, N: int) -> float:
    """% del tiempo que los agentes están ocupados en llamada. Ideal: 75-85%."""
    if N == 0:
        return 0.0
    return min(1.0, A / N)


def average_speed_of_answer(A: float, N: int, aht_seconds: float) -> float:
    """ASA: tiempo promedio de espera en cola, en segundos."""
    if N <= A:
        return float("inf")
    pw = erlang_c_prob_wait(A, N)
    return (pw * aht_seconds) / (N - A)


@dataclass
class StaffingResult:
    calls: int
    aht_seconds: float
    interval_seconds: int
    traffic_erlangs: float
    agents_erlang: int          # agentes matemáticamente necesarios (sin buffer)
    agents_final: int           # agentes finales, con shrinkage aplicado (recomendado a programar)
    service_level_pct: float
    occupancy_pct: float
    asa_seconds: float


def required_agents(
    calls: int,
    aht_seconds: float,
    interval_seconds: int = 3600,
    target_service_level: float = 0.95,   # 95% -> máxima prioridad al servicio
    target_answer_seconds: float = 20,     # contestadas en 20s
    max_occupancy: float = 0.85,           # no forzar agentes a más de 85% ocupación
    shrinkage: float = 0.10,               # % del tiempo pagado que NO es atención
                                            # (descansos, baños, capacitación, breaks, ausentismo)
) -> StaffingResult:
    """
    Calcula cuántos agentes se necesitan en un intervalo dado.

    shrinkage es CLAVE: si programas exactamente los agentes "matemáticos" del Erlang C,
    en la práctica te quedas corto porque la gente tiene descansos, va al baño, se enferma,
    tiene capacitaciones, etc. Un shrinkage típico de call center es 25%-35%.
    """
    if calls == 0:
        return StaffingResult(
            calls=0, aht_seconds=aht_seconds, interval_seconds=interval_seconds,
            traffic_erlangs=0, agents_erlang=0, agents_final=0,
            service_level_pct=1.0, occupancy_pct=0.0, asa_seconds=0.0,
        )

    A = (calls * aht_seconds) / interval_seconds

    # Buscar el N mínimo que cumple el nivel de servicio objetivo
    N = max(1, math.ceil(A))  # arrancar en algo mayor a la carga
    while True:
        sl = service_level(A, N, aht_seconds, target_answer_seconds)
        occ = occupancy(A, N)
        if sl >= target_service_level and occ <= max_occupancy:
            break
        N += 1
        if N > 1000:  # salvaguarda
            break

    agents_erlang = N
    # Aplicar shrinkage: si necesito N agentes EN EL TELÉFONO, y solo el (1-shrinkage)
    # de las horas pagadas es tiempo real de atención, necesito programar más personas.
    agents_final = math.ceil(agents_erlang / (1 - shrinkage))

    final_sl = service_level(A, agents_erlang, aht_seconds, target_answer_seconds)
    final_occ = occupancy(A, agents_erlang)
    final_asa = average_speed_of_answer(A, agents_erlang, aht_seconds)

    return StaffingResult(
        calls=calls,
        aht_seconds=aht_seconds,
        interval_seconds=interval_seconds,
        traffic_erlangs=round(A, 2),
        agents_erlang=agents_erlang,
        agents_final=agents_final,
        service_level_pct=round(final_sl * 100, 1),
        occupancy_pct=round(final_occ * 100, 1),
        asa_seconds=round(final_asa, 1) if final_asa != float("inf") else None,
    )
