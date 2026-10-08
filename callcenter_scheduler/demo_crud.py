"""
demo_crud.py
Muestra las operaciones CRUD del módulo de personal:
crear, editar disponibilidad, poner permiso de vacaciones, editar horas contractuales, eliminar (soft delete).
"""

from db import (
    crear_empleado, listar_empleados, obtener_empleado, actualizar_empleado, eliminar_empleado,
    set_disponibilidad, obtener_disponibilidad,
    crear_permiso, listar_permisos,
)

print("1) CREAR un nuevo asesor (recién contratado)")
nuevo_id = crear_empleado("LAURA RAMIREZ", horas_min_semana=22, horas_max_semana=36)
print(f"   -> Creado con id={nuevo_id}")

print("\n2) EDITAR su disponibilidad (ej. solo puede lunes a viernes en la tarde)")
for dia in ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]:
    set_disponibilidad(nuevo_id, dia, "rango", "14:00", "21:00")
set_disponibilidad(nuevo_id, "Sábado", "no_disponible")
set_disponibilidad(nuevo_id, "Domingo", "no_disponible")
print("   -> Disponibilidad guardada:", obtener_disponibilidad(nuevo_id))

print("\n3) AJUSTAR sus horas contractuales (ej. la subieron a medio tiempo distinto)")
actualizar_empleado(nuevo_id, horas_max_semana=30)
print("   -> Empleado actualizado:", obtener_empleado(nuevo_id))

print("\n4) REGISTRAR un permiso de vacaciones")
permiso_id = crear_permiso(nuevo_id, "vacaciones", "2026-09-15", "2026-09-22", comentario="Vacaciones anuales")
print(f"   -> Permiso creado id={permiso_id}:", listar_permisos(nuevo_id))

print("\n5) ELIMINAR (baja lógica, conserva historial de horarios pasados)")
eliminar_empleado(nuevo_id)
print("   -> ¿Sigue en la lista de activos?", any(e["id"] == nuevo_id for e in listar_empleados(solo_activos=True)))
print("   -> ¿Sigue existiendo en la BD (para no romper reportes históricos)?", obtener_empleado(nuevo_id) is not None)
