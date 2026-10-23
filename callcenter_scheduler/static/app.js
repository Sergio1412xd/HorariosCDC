const API = "/api";
const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

// ---------- Tema (oscuro/claro) ----------

function aplicarTema(tema) {
  document.documentElement.setAttribute("data-theme", tema);
  localStorage.setItem("tema_horarios_cdc", tema);
  const iconoLuna = document.getElementById("theme-icon-luna");
  const iconoSol = document.getElementById("theme-icon-sol");
  if (iconoLuna && iconoSol) {
    iconoLuna.style.display = tema === "dark" ? "none" : "";
    iconoSol.style.display = tema === "dark" ? "" : "none";
  }
  const btn = document.getElementById("theme-toggle-btn");
  if (btn) btn.title = tema === "dark" ? "Cambiar a modo claro" : "Cambiar a modo oscuro";
  if (window.Chart) {
    Chart.defaults.color = tema === "dark" ? "#9CA0AC" : "#6B6E76";
    Chart.defaults.borderColor = tema === "dark" ? "#383B45" : "#E3E1DB";
  }
}

function alternarTema() {
  const actual = document.documentElement.getAttribute("data-theme") || "light";
  aplicarTema(actual === "dark" ? "light" : "dark");
}

function alternarVerPassword() {
  const input = document.getElementById("login-password");
  const mostrando = input.type === "text";
  input.type = mostrando ? "password" : "text";
  document.getElementById("pw-icon-ojo").style.display = mostrando ? "" : "none";
  document.getElementById("pw-icon-ojo-tachado").style.display = mostrando ? "none" : "";
}

aplicarTema(localStorage.getItem("tema_horarios_cdc") || "light");

// ---------- Navegación ----------

function actualizarIndicadorGuardado() {
  const btn = document.getElementById("btn-guardar-historial");
  if (!btn) return;
  btn.classList.toggle("sin-guardar", !horarioGuardadoActual);
  btn.textContent = horarioGuardadoActual ? "💾 Guardar este horario en el Historial" : "💾 Guardar este horario en el Historial (sin guardar)";
}

document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", async () => {
    const vistaDestino = btn.dataset.view;
    const vistaActual = document.querySelector(".nav-item.active")?.dataset.view;
    if (vistaActual === "horarios" && vistaDestino !== "horarios" && ultimoHorarioGenerado && !horarioGuardadoActual) {
      const seguir = await confirmarAccion(
        "Generaste un horario que todavía no has guardado en el Historial. Si sales ahora, se pierde. ¿Seguro que quieres salir sin guardarlo?",
        { textoBoton: "Salir sin guardar" }
      );
      if (!seguir) return;
    }
    mostrarVista(vistaDestino);
    cerrarSidebarMovil();
  });
});

function alternarSidebarMovil() {
  document.getElementById("sidebar-nav").classList.toggle("abierto");
  document.getElementById("sidebar-backdrop").classList.toggle("visible");
}

function cerrarSidebarMovil() {
  document.getElementById("sidebar-nav").classList.remove("abierto");
  document.getElementById("sidebar-backdrop").classList.remove("visible");
}

function mostrarVista(nombre) {
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
  document.getElementById(`view-${nombre}`).classList.add("active");
  document.querySelector(`.nav-item[data-view="${nombre}"]`)?.classList.add("active");

  if (nombre === "importar") { /* nada que precargar */ }
  if (nombre === "personal") cargarEmpleados();
  if (nombre === "disponibilidad") cargarSelectEmpleados();
  if (nombre === "permisos") cargarPermisos();
  if (nombre === "metricas") cargarMetricas();
  if (nombre === "horarios") inicializarVistaHorarios();
  if (nombre === "historial") cargarHistorialHorarios();
  if (nombre === "comparar") inicializarComparador();
  if (nombre === "brecha") { inicializarVistaBrecha(); cargarBrecha(); }
  if (nombre === "tarifas") cargarTarifas();
  if (nombre === "turnos") cargarPlantillas();
    if (nombre === "usuarios") cargarUsuarios();
  if (nombre === "auditoria") { cargarFiltrosAuditoria(); cargarAuditoria(); }
  if (nombre === "mi-cuenta") cargarMiCuenta();
  if (nombre === "configuracion") cargarConfiguracion();
  if (nombre === "mi-cuenta") { document.getElementById("mi-cuenta-info").textContent = `Conectado como ${usuarioActual.username} (${usuarioActual.rol})`; }
}

// ---------- Helpers ----------

async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(API + path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (e) {
    alert("No se pudo conectar con el servidor. ¿Sigue corriendo 'uvicorn main:app'?");
    throw e;
  }
  if (res.status === 401 && path !== "/login") {
    mostrarPantallaLogin("Tu sesión expiró. Ingresa de nuevo.");
    throw new Error("No autenticado");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(data?.detail || "Error en la solicitud");
  }
  return data;
}

function abrirModal(id) { document.getElementById(id).classList.add("open"); }
function cerrarModal(id) {
  document.getElementById(id).classList.remove("open");
  document.querySelectorAll(`#${id} .error-text`).forEach(e => e.textContent = "");
}

// Reemplaza al confirm() nativo del navegador con un modal propio, consistente con el
// resto de la interfaz. Uso: if (!(await confirmarAccion("¿Seguro?"))) return;
function confirmarAccion(mensaje, { textoBoton = "Confirmar", peligroso = true } = {}) {
  return new Promise(resolve => {
    document.getElementById("confirmar-mensaje").textContent = mensaje;
    document.getElementById("confirmar-icono").textContent = peligroso ? "⚠️" : "❓";
    const btnAceptar = document.getElementById("confirmar-btn-aceptar");
    const btnCancelar = document.getElementById("confirmar-btn-cancelar");
    btnAceptar.textContent = textoBoton;

    const limpiar = (resultado) => {
      cerrarModal("modal-confirmar");
      btnAceptar.removeEventListener("click", onAceptar);
      btnCancelar.removeEventListener("click", onCancelar);
      resolve(resultado);
    };
    const onAceptar = () => limpiar(true);
    const onCancelar = () => limpiar(false);

    btnAceptar.addEventListener("click", onAceptar);
    btnCancelar.addEventListener("click", onCancelar);
    abrirModal("modal-confirmar");
  });
}

// ---------- PERSONAL ----------

let validacionCache = {};

async function cargarEmpleados() {
  const [empleados, validacion] = await Promise.all([
    api("/empleados"),
    api("/disponibilidad/validacion"),
  ]);
  validacionCache = Object.fromEntries(validacion.map(v => [v.empleado, v]));

  const tbody = document.getElementById("tabla-empleados");

  if (empleados.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8">
      <div class="empty-state">
        Todavía no hay ningún asesor cargado en esta base de datos.<br>
        <a onclick="mostrarVista('importar')">Ir a Importar Datos →</a>
      </div>
    </td></tr>`;
    return;
  }

  tbody.innerHTML = "";
  // Al recargar la lista, se olvida cualquier selección anterior para no arrastrar ids
  // que ya no correspondan a lo que se ve en pantalla.
  empleadosSeleccionados.clear();
  actualizarBarraSeleccionEmpleados();

  empleados.forEach(emp => {
    const val = validacionCache[emp.nombre];
    const tieneAlerta = val && val.alertas.length > 0;
    const badge = tieneAlerta
      ? `<span class="badge badge-alerta" title="${val.alertas.join(' · ')}">Revisar</span>`
      : `<span class="badge badge-ok">OK</span>`;

    const tr = document.createElement("tr");
    const cedulaHtml = emp.cedula
      ? emp.cedula
      : `<button class="btn-icon" style="color:var(--rust)" onclick="editarCedula(${emp.id}, '${emp.nombre.replace(/'/g, "")}')">+ Agregar</button>`;
    const badgeExtra = emp.permite_horas_extra
      ? `<span class="badge badge-ok" title="Autorizado">+${emp.max_horas_extra_semana}h/sem</span>`
      : `<span style="color:var(--text-muted); font-size:11.5px;">No</span>`;
    tr.innerHTML = `
      <td><input type="checkbox" class="chk-empleado" data-id="${emp.id}" onchange="toggleSeleccionEmpleado(${emp.id}, this.checked)"></td>
      <td>${emp.nombre}</td>
      <td>${cedulaHtml}</td>
      <td>${emp.horas_min_dia}h – ${emp.horas_max_dia}h</td>
      <td>${emp.horas_min_semana}h – ${emp.horas_max_semana}h</td>
      <td>${badge}</td>
      <td>${badgeExtra} <button class="btn-icon" onclick='abrirModalHorasExtra(${emp.id}, "${emp.nombre.replace(/'/g, "")}", ${emp.permite_horas_extra}, ${emp.max_horas_extra_semana})'>Gestionar</button></td>
      <td>
        <button class="btn-icon" onclick='abrirModalEditarEmpleado(${emp.id}, ${JSON.stringify(emp.nombre)}, ${JSON.stringify(emp.cedula)}, ${emp.horas_min_dia}, ${emp.horas_max_dia}, ${emp.horas_min_semana}, ${emp.horas_max_semana})'>Editar</button>
        <button class="btn-icon" onclick="eliminarEmpleado(${emp.id}, '${emp.nombre.replace(/'/g, "")}')">Eliminar</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function editarCedula(id, nombre) {
  const cedula = prompt(`Número de cédula de ${nombre}:`);
  if (!cedula) return;
  await api(`/empleados/${id}`, { method: "PUT", body: JSON.stringify({ cedula: cedula.trim() }) });
  cargarEmpleados();
}

let empleadoEditandoId = null;

async function abrirModalNuevoEmpleado() {
  empleadoEditandoId = null;
  document.getElementById("modal-empleado-titulo").textContent = "Nuevo asesor";
  document.getElementById("btn-guardar-empleado").textContent = "Guardar";
  document.getElementById("emp-nombre").value = "";
  document.getElementById("emp-cedula").value = "";
  document.getElementById("emp-error").textContent = "";
  try {
    const defaults = await api("/configuracion/defaults-empleado");
    document.getElementById("emp-min-dia").value = defaults.horas_min_dia;
    document.getElementById("emp-max-dia").value = defaults.horas_max_dia;
    document.getElementById("emp-min-semana").value = defaults.horas_min_semana;
    document.getElementById("emp-max-semana").value = defaults.horas_max_semana;
  } catch (e) {
    document.getElementById("emp-min-dia").value = 4;
    document.getElementById("emp-max-dia").value = 8;
    document.getElementById("emp-min-semana").value = 22;
    document.getElementById("emp-max-semana").value = 36;
  }
  abrirModal("modal-empleado");
}

function abrirModalEditarEmpleado(id, nombre, cedula, minDia, maxDia, minSemana, maxSemana) {
  empleadoEditandoId = id;
  document.getElementById("modal-empleado-titulo").textContent = "Editar asesor";
  document.getElementById("btn-guardar-empleado").textContent = "Guardar cambios";
  document.getElementById("emp-nombre").value = nombre;
  document.getElementById("emp-cedula").value = cedula || "";
  document.getElementById("emp-min-dia").value = minDia;
  document.getElementById("emp-max-dia").value = maxDia;
  document.getElementById("emp-min-semana").value = minSemana;
  document.getElementById("emp-max-semana").value = maxSemana;
  document.getElementById("emp-error").textContent = "";
  abrirModal("modal-empleado");
}

async function guardarNuevoEmpleado() {
  const errEl = document.getElementById("emp-error");
  const nombre = document.getElementById("emp-nombre").value.trim();
  if (!nombre) { errEl.textContent = "El nombre es obligatorio."; return; }

  const payload = {
    nombre,
    cedula: document.getElementById("emp-cedula").value.trim() || null,
    horas_min_dia: parseFloat(document.getElementById("emp-min-dia").value),
    horas_max_dia: parseFloat(document.getElementById("emp-max-dia").value),
    horas_min_semana: parseFloat(document.getElementById("emp-min-semana").value),
    horas_max_semana: parseFloat(document.getElementById("emp-max-semana").value),
  };

  try {
    if (empleadoEditandoId) {
      await api(`/empleados/${empleadoEditandoId}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      await api("/empleados", { method: "POST", body: JSON.stringify(payload) });
    }
    cerrarModal("modal-empleado");
    cargarEmpleados();
  } catch (e) {
    errEl.textContent = e.message;
  }
}

async function eliminarEmpleado(id, nombre) {
  if (!(await confirmarAccion(`¿Dar de baja a ${nombre}? Su historial de horarios se conserva.`))) return;
  await api(`/empleados/${id}`, { method: "DELETE" });
  cargarEmpleados();
}

// ---------- DISPONIBILIDAD ----------

async function cargarSelectEmpleados() {
  const empleados = await api("/empleados");
  const select = document.getElementById("select-empleado-disp");
  const fullTime = empleados.filter(e => (e.tipo_contrato || "full_time") === "full_time");
  const partTime = empleados.filter(e => (e.tipo_contrato || "full_time") === "part_time");
  const opciones = grupo => grupo.map(e => `<option value="${e.id}">${e.nombre}</option>`).join("");
  select.innerHTML =
    (fullTime.length ? `<optgroup label="Full Time">${opciones(fullTime)}</optgroup>` : "") +
    (partTime.length ? `<optgroup label="Part Time">${opciones(partTime)}</optgroup>` : "");
  if (empleados.length) cargarDisponibilidad();
}

const HORARIO_OPERATIVO = { inicio: "11:00", fin: "23:00" };

function _horasEntre(hi, hf) {
  const [h1, m1] = hi.split(":").map(Number);
  const [h2, m2] = hf.split(":").map(Number);
  return (h2 * 60 + m2 - (h1 * 60 + m1)) / 60;
}

function _horasDelDia(d) {
  if (d.tipo === "completa") return _horasEntre(HORARIO_OPERATIVO.inicio, HORARIO_OPERATIVO.fin);
  if (d.tipo === "rango") return _horasEntre(d.hora_inicio, d.hora_fin);
  return 0;
}

async function cargarDisponibilidad() {
  const empId = document.getElementById("select-empleado-disp").value;
  if (!empId) return;
  if (Object.keys(validacionCache).length === 0) {
    const validacion = await api("/disponibilidad/validacion");
    validacionCache = Object.fromEntries(validacion.map(v => [v.empleado, v]));
  }
  const disp = await api(`/empleados/${empId}/disponibilidad`);

  let totalHoras = 0;
  let diasSinInfo = 0;

  const grid = document.getElementById("grid-disponibilidad");
  grid.innerHTML = DIAS.map(dia => {
    const d = disp[dia] || { tipo: "sin_informacion" };
    totalHoras += _horasDelDia(d);
    if (d.tipo === "sin_informacion") diasSinInfo++;

    return `
      <div class="disp-row" data-tipo="${d.tipo}" id="card-${dia}">
        <div class="disp-row-stripe"></div>
        <div class="disp-row-nombre">
          <h3>${dia}</h3>
          <div class="disp-day-horas" id="horas-${dia}">${_horasDelDia(d) > 0 ? _horasDelDia(d) + 'h disponibles' : 'Sin definir'}</div>
        </div>
        <div class="disp-tipo-toggle" id="toggle-${dia}">
          <button type="button" class="disp-tipo-btn ${d.tipo === 'completa' ? 'active' : ''}" data-tipo="completa" onclick="cambiarTipoDisponibilidad('${dia}','completa')">Todo el día</button>
          <button type="button" class="disp-tipo-btn ${d.tipo === 'rango' ? 'active' : ''}" data-tipo="rango" onclick="cambiarTipoDisponibilidad('${dia}','rango')">Rango</button>
          <button type="button" class="disp-tipo-btn ${d.tipo === 'no_disponible' ? 'active' : ''}" data-tipo="no_disponible" onclick="cambiarTipoDisponibilidad('${dia}','no_disponible')">No puede</button>
        </div>
        <div class="disp-rango-inputs" id="rango-${dia}" style="${d.tipo === 'rango' ? '' : 'visibility:hidden'}">
          <input type="time" id="ini-${dia}" value="${d.hora_inicio || '09:00'}" onchange="guardarDisponibilidad('${dia}')">
          <span>a</span>
          <input type="time" id="fin-${dia}" value="${d.hora_fin || '17:00'}" onchange="guardarDisponibilidad('${dia}')">
        </div>
      </div>
    `;
  }).join("");

  const val = validacionCache[document.getElementById("select-empleado-disp").selectedOptions[0]?.textContent];
  document.getElementById("disp-resumen").innerHTML = `
    <div class="disp-resumen-item">
      <div class="label">Horas disponibles / semana</div>
      <div class="value">${totalHoras.toFixed(0)}h</div>
    </div>
    <div class="disp-resumen-item">
      <div class="label">Días sin información</div>
      <div class="value" style="color:${diasSinInfo ? 'var(--rust)' : 'var(--green)'}">${diasSinInfo}</div>
    </div>
    <div class="disp-resumen-item">
      <div class="label">Estado</div>
      <div class="value">${val && val.alertas.length ? '<span class="badge badge-alerta">Revisar</span>' : '<span class="badge badge-ok">OK</span>'}</div>
    </div>
  `;
}

function cambiarTipoDisponibilidad(dia, tipo) {
  document.querySelectorAll(`#toggle-${dia} .disp-tipo-btn`).forEach(b => b.classList.toggle("active", b.dataset.tipo === tipo));
  document.getElementById(`rango-${dia}`).style.visibility = tipo === "rango" ? "visible" : "hidden";
  guardarDisponibilidad(dia);
}

async function guardarDisponibilidad(dia) {
  const empId = document.getElementById("select-empleado-disp").value;
  const tipo = document.querySelector(`#toggle-${dia} .disp-tipo-btn.active`).dataset.tipo;
  const payload = { dia_semana: dia, tipo };
  if (tipo === "rango") {
    payload.hora_inicio = document.getElementById(`ini-${dia}`).value;
    payload.hora_fin = document.getElementById(`fin-${dia}`).value;
  }
  try {
    await api(`/empleados/${empId}/disponibilidad`, { method: "PUT", body: JSON.stringify(payload) });
    document.getElementById(`card-${dia}`).dataset.tipo = tipo;
    const horasTxt = tipo === "completa" ? `${_horasEntre(HORARIO_OPERATIVO.inicio, HORARIO_OPERATIVO.fin)}h disponibles`
                    : tipo === "rango" ? `${_horasEntre(payload.hora_inicio, payload.hora_fin)}h disponibles` : "—";
    document.getElementById(`horas-${dia}`).textContent = horasTxt;

    const msg = document.getElementById("disp-guardado-msg");
    msg.textContent = `${dia}: guardado ✓`;
    msg.style.opacity = 1;
    setTimeout(() => { msg.style.opacity = 0; }, 1800);

    cargarDisponibilidad(); // refresca el resumen de horas totales
  } catch (e) {
    alert(e.message);
  }
}

async function aplicarRapido(tipo) {
  const empId = document.getElementById("select-empleado-disp").value;
  if (!empId) return;
  for (const dia of DIAS) {
    const payload = { dia_semana: dia, tipo };
    await api(`/empleados/${empId}/disponibilidad`, { method: "PUT", body: JSON.stringify(payload) });
  }
  cargarDisponibilidad();
}

async function copiarLunesALaborales() {
  const empId = document.getElementById("select-empleado-disp").value;
  if (!empId) return;
  const disp = await api(`/empleados/${empId}/disponibilidad`);
  const base = disp["Lunes"];
  if (!base) return;
  for (const dia of ["Martes", "Miércoles", "Jueves", "Viernes"]) {
    const payload = { dia_semana: dia, tipo: base.tipo };
    if (base.tipo === "rango") { payload.hora_inicio = base.hora_inicio; payload.hora_fin = base.hora_fin; }
    await api(`/empleados/${empId}/disponibilidad`, { method: "PUT", body: JSON.stringify(payload) });
  }
  cargarDisponibilidad();
}

// ---------- PERMISOS ----------

async function cargarPermisos() {
  const permisos = await api("/permisos");
  const empleados = await api("/empleados");
  const nombreDe = Object.fromEntries(empleados.map(e => [e.id, e.nombre]));

  const tbody = document.getElementById("tabla-permisos");
  tbody.innerHTML = permisos.map(p => `
    <tr>
      <td>${nombreDe[p.empleado_id] || "—"}</td>
      <td>${p.tipo.replace("_", " ")}</td>
      <td>${p.fecha_inicio}</td>
      <td>${p.fecha_fin}</td>
      <td>${p.comentario || ""}</td>
      <td><button class="btn-icon" onclick="eliminarPermiso(${p.id})">Eliminar</button></td>
    </tr>
  `).join("");
}

async function abrirModalNuevoPermiso() {
  const empleados = await api("/empleados");
  document.getElementById("permiso-empleado").innerHTML =
    empleados.map(e => `<option value="${e.id}">${e.nombre}</option>`).join("");
  document.getElementById("permiso-desde").value = "";
  document.getElementById("permiso-hasta").value = "";
  document.getElementById("permiso-comentario").value = "";
  abrirModal("modal-permiso");
}

async function guardarNuevoPermiso() {
  const errEl = document.getElementById("permiso-error");
  const empId = document.getElementById("permiso-empleado").value;
  const tipo = document.getElementById("permiso-tipo").value;
  const desde = document.getElementById("permiso-desde").value;
  const hasta = document.getElementById("permiso-hasta").value;
  const comentario = document.getElementById("permiso-comentario").value;

  if (!desde || !hasta) { errEl.textContent = "Selecciona ambas fechas."; return; }

  try {
    await api(`/empleados/${empId}/permisos`, {
      method: "POST",
      body: JSON.stringify({ tipo, fecha_inicio: desde, fecha_fin: hasta, comentario }),
    });
    cerrarModal("modal-permiso");
    cargarPermisos();
  } catch (e) {
    errEl.textContent = e.message;
  }
}

async function eliminarPermiso(id) {
  if (!(await confirmarAccion("¿Eliminar este permiso?"))) return;
  await api(`/permisos/${id}`, { method: "DELETE" });
  cargarPermisos();
}

// ---------- Init ----------
verificarSesion();

// ---------- AUTENTICACIÓN ----------

let usuarioActual = null;

function mostrarPantallaLogin(mensajeError = "") {
  document.getElementById("app-root").style.display = "none";
  document.getElementById("login-screen").style.display = "flex";
  document.getElementById("login-error").textContent = mensajeError;
  document.getElementById("login-password").value = "";
}

function mostrarApp() {
  document.getElementById("login-screen").style.display = "none";
  document.getElementById("app-root").style.display = "block";

  document.getElementById("nav-usuario-actual").textContent =
    `${usuarioActual.username} (${usuarioActual.rol === "superadmin" ? "Superadmin" : "Admin"})`;
  document.getElementById("nav-usuario-avatar").textContent = usuarioActual.username.charAt(0).toUpperCase();

  // Solo superadmin ve la pestaña de Usuarios
  document.getElementById("nav-usuarios").style.display =
    usuarioActual.rol === "superadmin" ? "block" : "none";
  document.getElementById("nav-auditoria").style.display =
    usuarioActual.rol === "superadmin" ? "block" : "none";
  document.getElementById("nav-configuracion").style.display =
    usuarioActual.rol === "superadmin" ? "block" : "none";
  document.getElementById("danger-zone-llamadas").style.display =
    usuarioActual.rol === "superadmin" ? "block" : "none";

  // Si el usuario tiene una lista de módulos permitidos (no es superadmin, y se le
  // restringió específicamente), ocultar del menú lo que no tenga permitido.
  if (usuarioActual.rol !== "superadmin" && usuarioActual.modulos_permitidos != null) {
    document.querySelectorAll(".nav-item[data-view]").forEach(btn => {
      const modulo = btn.dataset.view;
      if (modulo !== "mi-cuenta" && !usuarioActual.modulos_permitidos.includes(modulo)) {
        btn.style.display = "none";
      }
    });
  }

  cargarEmpleados();
  cargarNotificaciones();
  setInterval(cargarNotificaciones, 5 * 60 * 1000); // refrescar cada 5 minutos
}

async function verificarSesion() {
  try {
    const res = await fetch(API + "/me");
    if (!res.ok) { mostrarPantallaLogin(); return; }
    usuarioActual = await res.json();
    mostrarApp();
  } catch (e) {
    mostrarPantallaLogin();
  }
}

async function hacerLogin() {
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  const errEl = document.getElementById("login-error");
  if (!username || !password) { errEl.textContent = "Ingresa usuario y contraseña."; return; }

  try {
    const res = await fetch(API + "/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.detail || "Error de acceso"; return; }
    usuarioActual = data;
    errEl.textContent = "";
    mostrarApp();
  } catch (e) {
    errEl.textContent = "No se pudo conectar con el servidor.";
  }
}

document.getElementById("login-password")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") hacerLogin();
});

async function hacerLogout() {
  await fetch(API + "/logout", { method: "POST" });
  usuarioActual = null;
  mostrarPantallaLogin();
}

async function guardarNuevaPassword() {
  const errEl = document.getElementById("cambiar-pass-error");
  const actual = document.getElementById("cambiar-pass-actual").value;
  const nueva = document.getElementById("cambiar-pass-nueva").value;
  if (nueva.length < 8) { errEl.textContent = "La nueva contraseña debe tener al menos 8 caracteres."; return; }
  try {
    await api("/cambiar-password", {
      method: "POST",
      body: JSON.stringify({ password_actual: actual, password_nueva: nueva }),
    });
    usuarioActual.debe_cambiar_password = false;
    cerrarModal("modal-cambiar-password");
  } catch (e) {
    errEl.textContent = e.message;
  }
}

async function cambiarMiPassword() {
  const msg = document.getElementById("cuenta-pass-msg");
  const actual = document.getElementById("cuenta-pass-actual").value;
  const nueva = document.getElementById("cuenta-pass-nueva").value;
  if (nueva.length < 8) {
    msg.style.color = "var(--rust)"; msg.textContent = "La nueva contraseña debe tener al menos 8 caracteres."; return;
  }
  try {
    await api("/cambiar-password", {
      method: "POST",
      body: JSON.stringify({ password_actual: actual, password_nueva: nueva }),
    });
    msg.style.color = "var(--green)"; msg.textContent = "Contraseña actualizada ✓";
    document.getElementById("cuenta-pass-actual").value = "";
    document.getElementById("cuenta-pass-nueva").value = "";
  } catch (e) {
    msg.style.color = "var(--rust)"; msg.textContent = e.message;
  }
}

// ---------- USUARIOS (solo superadmin) ----------

async function cargarUsuarios() {
  document.getElementById("mi-cuenta-info").textContent = `Conectado como ${usuarioActual.username}`;
  try {
    const usuarios = await api("/usuarios");
    document.getElementById("tabla-usuarios").innerHTML = usuarios.map(u => {
      const modulosTexto = u.rol === "superadmin"
        ? '<span style="color:var(--text-muted);">Todos (superadmin)</span>'
        : (u.modulos_permitidos ? u.modulos_permitidos.join(", ") : '<span style="color:var(--text-muted);">Todos</span>');
      return `
      <tr>
        <td>${u.username}</td>
        <td>${u.rol === "superadmin" ? "Superadmin" : "Admin"}</td>
        <td style="font-size:12px;">${modulosTexto}</td>
        <td>${u.activo ? '<span class="badge badge-ok">Activo</span>' : '<span class="badge badge-alerta">Inactivo</span>'}</td>
        <td>
          ${u.rol !== "superadmin" ? `<button class="btn-icon" onclick='abrirModalEditarModulos(${u.id}, "${u.username}", ${JSON.stringify(u.modulos_permitidos)})'>Módulos</button>` : ""}
          <button class="btn-icon" onclick="eliminarUsuario(${u.id}, '${u.username}')">Desactivar</button>
          <button class="btn-icon" style="color:var(--rust);" onclick="eliminarUsuarioDefinitivo(${u.id}, '${u.username}')">Eliminar</button>
        </td>
      </tr>`;
    }).join("");
  } catch (e) {
    document.getElementById("tabla-usuarios").innerHTML =
      `<tr><td colspan="5" style="text-align:center; color:var(--text-muted);">${e.message}</td></tr>`;
  }
}

let modulosDisponiblesCache = [];

async function _asegurarModulosDisponibles() {
  if (!modulosDisponiblesCache.length) {
    modulosDisponiblesCache = await api("/modulos-disponibles");
  }
}

const NOMBRES_MODULOS = {
  inicio: "Inicio", importar: "Importar Datos", personal: "Personal", disponibilidad: "Disponibilidad",
  permisos: "Permisos", metricas: "Métricas", turnos: "Turnos", horarios: "Horarios",
  historial: "Historial", comparar: "Comparar", brecha: "Brecha de Personal",
};

async function onCambioRolUsuario() {
  const rol = document.getElementById("usuario-rol").value;
  document.getElementById("usuario-modulos-wrap").style.display = rol === "superadmin" ? "none" : "block";
}

async function onToggleTodosModulos() {
  const todos = document.getElementById("usuario-todos-modulos").checked;
  const cont = document.getElementById("usuario-modulos-checkboxes");
  cont.style.display = todos ? "none" : "grid";
  if (!todos) {
    await _asegurarModulosDisponibles();
    if (!cont.children.length) {
      cont.innerHTML = modulosDisponiblesCache.map(m => `
        <label class="dia-checkbox-item"><input type="checkbox" value="${m}" checked> ${NOMBRES_MODULOS[m] || m}</label>
      `).join("");
    }
  }
}

async function abrirModalNuevoUsuario() {
  document.getElementById("usuario-username").value = "";
  document.getElementById("usuario-password").value = "";
  document.getElementById("usuario-rol").value = "admin";
  document.getElementById("usuario-todos-modulos").checked = true;
  document.getElementById("usuario-modulos-checkboxes").style.display = "none";
  document.getElementById("usuario-modulos-checkboxes").innerHTML = "";
  document.getElementById("usuario-modulos-wrap").style.display = "block";
  document.querySelector("#modal-usuario h2").textContent = "Nuevo usuario";
  document.querySelectorAll("#usuario-username, #usuario-password, #usuario-rol").forEach(el => el.style.display = "");
  document.querySelectorAll("#modal-usuario label").forEach(el => el.style.display = "");
  document.getElementById("modal-usuario").dataset.modo = "crear";
  await _asegurarModulosDisponibles();
  abrirModal("modal-usuario");
}

async function abrirModalEditarModulos(id, username, modulosActuales) {
  document.querySelector("#modal-usuario h2").textContent = `Módulos de ${username}`;
  document.getElementById("usuario-username").parentElement.style.display = "none";
  document.getElementById("usuario-password").parentElement.style.display = "none";
  document.getElementById("usuario-rol").parentElement.style.display = "none";
  document.getElementById("usuario-modulos-wrap").style.display = "block";
  document.getElementById("modal-usuario").dataset.modo = "editar";
  document.getElementById("modal-usuario").dataset.userId = id;

  await _asegurarModulosDisponibles();
  const todos = modulosActuales === null;
  document.getElementById("usuario-todos-modulos").checked = todos;
  const cont = document.getElementById("usuario-modulos-checkboxes");
  cont.style.display = todos ? "none" : "grid";
  cont.innerHTML = modulosDisponiblesCache.map(m => `
    <label class="dia-checkbox-item"><input type="checkbox" value="${m}" ${!modulosActuales || modulosActuales.includes(m) ? "checked" : ""}> ${NOMBRES_MODULOS[m] || m}</label>
  `).join("");
  abrirModal("modal-usuario");
}

function _modulosSeleccionados() {
  const todos = document.getElementById("usuario-todos-modulos").checked;
  if (todos) return null;
  return Array.from(document.querySelectorAll("#usuario-modulos-checkboxes input:checked")).map(el => el.value);
}

async function guardarNuevoUsuario() {
  const errEl = document.getElementById("usuario-error");
  const modo = document.getElementById("modal-usuario").dataset.modo || "crear";

  if (modo === "editar") {
    const userId = document.getElementById("modal-usuario").dataset.userId;
    try {
      await api(`/usuarios/${userId}/modulos`, { method: "PUT", body: JSON.stringify({ modulos_permitidos: _modulosSeleccionados() }) });
      cerrarModal("modal-usuario");
      cargarUsuarios();
    } catch (e) {
      errEl.textContent = e.message;
    }
    return;
  }

  const username = document.getElementById("usuario-username").value.trim();
  const password = document.getElementById("usuario-password").value;
  const rol = document.getElementById("usuario-rol").value;
  if (!username || password.length < 8) {
    errEl.textContent = "Usuario y contraseña (mín. 8 caracteres) son obligatorios.";
    return;
  }
  try {
    await api("/usuarios", { method: "POST", body: JSON.stringify({ username, password, rol, modulos_permitidos: _modulosSeleccionados() }) });
    cerrarModal("modal-usuario");
    cargarUsuarios();
  } catch (e) {
    errEl.textContent = e.message;
  }
}

async function eliminarUsuario(id, username) {
  if (!(await confirmarAccion(`¿Desactivar el acceso de ${username}?`))) return;
  try {
    await api(`/usuarios/${id}`, { method: "DELETE" });
    cargarUsuarios();
  } catch (e) {
    alert(e.message);
  }
}

async function eliminarUsuarioDefinitivo(id, username) {
  const confirmado = await confirmarAccion(
    `¿Eliminar por completo la cuenta de ${username}? A diferencia de "Desactivar", esto no se puede deshacer -- tendrías que crear la cuenta de nuevo desde cero. Su historial de auditoría se conserva.`,
    { textoBoton: "Sí, eliminar definitivamente" }
  );
  if (!confirmado) return;
  try {
    await api(`/usuarios/${id}/definitivo`, { method: "DELETE" });
    cargarUsuarios();
  } catch (e) {
    alert(e.message);
  }
}

function _colorAccionAuditoria(accion) {
  if (accion.startsWith("eliminar") || accion.startsWith("borrar") || accion.includes("desactivar")) return "badge-alerta";
  return "badge-ok";
}

async function cargarFiltrosAuditoria() {
  try {
    const { acciones, usuarios } = await api("/auditoria/filtros");
    const selAccion = document.getElementById("aud-accion");
    const selUsuario = document.getElementById("aud-usuario");
    selAccion.innerHTML = '<option value="">Todos</option>' +
      acciones.map(a => `<option value="${a}">${a.replace(/_/g, " ")}</option>`).join("");
    selUsuario.innerHTML = '<option value="">Todos</option>' +
      usuarios.map(u => `<option value="${u}">${u}</option>`).join("");
  } catch (e) {
    // silencioso -- los filtros quedan vacíos, la tabla igual carga sin filtrar
  }
}

function limpiarFiltrosAuditoria() {
  document.getElementById("aud-busqueda").value = "";
  document.getElementById("aud-accion").value = "";
  document.getElementById("aud-usuario").value = "";
  document.getElementById("aud-desde").value = "";
  document.getElementById("aud-hasta").value = "";
  cargarAuditoria();
}

async function cargarAuditoria() {
  const tbody = document.getElementById("tabla-auditoria");
  const params = new URLSearchParams();
  const busqueda = document.getElementById("aud-busqueda")?.value.trim();
  const accion = document.getElementById("aud-accion")?.value;
  const usuario = document.getElementById("aud-usuario")?.value;
  const desde = document.getElementById("aud-desde")?.value;
  const hasta = document.getElementById("aud-hasta")?.value;
  if (busqueda) params.set("busqueda", busqueda);
  if (accion) params.set("accion", accion);
  if (usuario) params.set("usuario", usuario);
  if (desde) params.set("fecha_inicio", desde);
  if (hasta) params.set("fecha_fin", hasta);

  try {
    const registros = await api(`/auditoria${params.toString() ? "?" + params.toString() : ""}`);
    tbody.innerHTML = registros.length
      ? registros.map(r => {
          const fecha = new Date(r.fecha_hora);
          const fechaTexto = fecha.toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short" });
          return `<tr>
            <td style="white-space:nowrap;">${fechaTexto}</td>
            <td>${r.username}</td>
            <td><span class="badge ${_colorAccionAuditoria(r.accion)}" style="text-transform:none;">${r.accion.replace(/_/g, " ")}</span></td>
            <td style="font-size:12px; color:var(--text-muted);">${r.detalle || "—"}</td>
          </tr>`;
        }).join("")
      : `<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">No hay registros con esos filtros</td></tr>`;
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">${e.message}</td></tr>`;
  }
}

// ---------- HORARIOS ----------

function _proximoLunes() {
  const hoy = new Date();
  const dia = hoy.getDay(); // 0=domingo
  const diasHastaLunes = dia === 1 ? 7 : (8 - dia) % 7 || 7;
  const lunes = new Date(hoy);
  lunes.setDate(hoy.getDate() + diasHastaLunes);
  return lunes.toISOString().slice(0, 10);
}

function inicializarVistaHorarios() {
  const input = document.getElementById("horario-fecha");
  if (!input.value) input.value = _proximoLunes();
  actualizarBadgeModo();
  cargarSemanasDisponibles();
  document.getElementById("ultra-productividad-estado").textContent = modoUltraProductividad ? "Encendido" : "Apagado";
  document.getElementById("btn-ultra-productividad").classList.toggle("activo", modoUltraProductividad);
}

let semanasDisponiblesCache = [];
let ultimoHorarioGenerado = null;
let horarioGuardadoActual = true; // true hasta que se genere algo nuevo sin guardar
let ultimoHorarioParametros = null;

async function cargarSemanasDisponibles() {
  try {
    semanasDisponiblesCache = await api("/semanas-disponibles");
    const cont = document.getElementById("horario-semanas-select");
    const msgVacio = document.getElementById("horario-semanas-vacio-msg");
    if (!semanasDisponiblesCache.length) {
      cont.innerHTML = "";
      msgVacio.style.display = "block";
      return;
    }
    msgVacio.style.display = "none";
    cont.innerHTML = semanasDisponiblesCache.map(s => `
      <option value="${s.fecha_lunes}" ${s.tiene_festivo ? 'style="color:var(--rust); font-weight:600;"' : ''}>
        ${s.tiene_festivo ? '⭐ ' : ''}Sem ${s.numero_semana} — ${s.fecha_lunes} a ${s.fecha_domingo} (${s.llamadas_contestadas.toLocaleString('es-CO')} llam.)${s.tiene_festivo ? ' · festivo: ' + s.festivos.join(', ') : ''}
      </option>
    `).join("");
  } catch (e) {
    // sin datos cargados todavía, no pasa nada -- se queda en modo automático
  }
}

function cambiarModoBaseDemanda(modo) {
  document.getElementById("btn-modo-automatico").classList.toggle("active", modo === "automatico");
  document.getElementById("btn-modo-especificas").classList.toggle("active", modo === "especificas");
  document.getElementById("horario-semanas-especificas-wrap").style.display = modo === "especificas" ? "block" : "none";
}

function _semanasBaseSeleccionadas() {
  const modoEspecificas = document.getElementById("btn-modo-especificas").classList.contains("active");
  if (!modoEspecificas) return null;
  const seleccionadas = Array.from(document.getElementById("horario-semanas-select").selectedOptions).map(o => o.value);
  return seleccionadas.length ? seleccionadas.join(",") : null;
}

async function actualizarBadgeModo() {
  const badge = document.getElementById("horario-modo-badge");
  try {
    const plantillas = await api("/plantillas-turno");
    const activas = plantillas.filter(p => p.activo);
    badge.innerHTML = activas.length
      ? `<span class="badge badge-ok">📋 Modo Plantillas — ${activas.length} horario(s) válido(s) definidos</span>`
      : `<span class="badge badge-modo-libre">🔓 Modo Libre — sin plantillas, turnos ajustados a la demanda</span>
         <a onclick="mostrarVista('turnos')" style="margin-left:8px; font-size:12px; color:var(--amber-dark); cursor:pointer;">Definir plantillas →</a>`;
  } catch (e) {
    badge.innerHTML = "";
  }
}

function avisoMetaExtrema(idSelect, idAviso) {
  const valor = parseFloat(document.getElementById(idSelect).value);
  const div = document.getElementById(idAviso);
  if (valor >= 1.0) {
    div.innerHTML = `<div class="productividad-nota tono-rust">
      ⚠️ <strong>100% es una meta teórica</strong> — en la práctica pide muchísimos más agentes de los necesarios
      (en pruebas, hasta 4x más agente-horas que al 95%, con ocupación real de ~8%, es decir, la gente estaría
      la mayor parte del turno sin hacer nada). Úsalo solo para ver el techo matemático, no como meta operativa real.
    </div>`;
  } else if (valor >= 0.98) {
    div.innerHTML = `<div class="productividad-nota tono-rust">
      ⚠️ 98% ya empieza a pedir bastante más personal que 95% para ganar poco margen adicional de servicio.
    </div>`;
  } else {
    div.innerHTML = "";
  }
}

let modoUltraProductividad = true; // ON por defecto -- meta 85% (normal sería 95%)

function toggleModoUltraProductividad() {
  modoUltraProductividad = !modoUltraProductividad;
  document.getElementById("ultra-productividad-estado").textContent = modoUltraProductividad ? "Encendido" : "Apagado";
  document.getElementById("btn-ultra-productividad").classList.toggle("activo", modoUltraProductividad);
  document.getElementById("nota-productividad")?.remove();
  generarHorario();
}

async function calcularContratacionMeta() {
  const fecha = document.getElementById("horario-fecha").value || _proximoLunes();
  const shrinkage = "0.10";
  const meta = document.getElementById("horario-meta-contratacion").value;
  const cont = document.getElementById("horario-contratacion-meta");
  cont.innerHTML = "<div class='loading-spinner'><span class='spinner'></span> Simulando...</div>";

  const metaGeneracion = ultimoHorarioParametros?.target_service_level;
  const notaMetaDistinta = (metaGeneracion != null && Math.round(metaGeneracion * 100) !== Math.round(meta * 100))
    ? ` <span style="font-weight:400;">— distinto de la meta con la que generaste este horario (${Math.round(metaGeneracion*100)}%, con la que arriba ves "Horas sin cubrir").</span>`
    : "";

  try {
    const data = await api(`/brecha-personal?fecha_lunes=${fecha}&shrinkage=${shrinkage}&target_service_level=${meta}`);
    if (data.asesores_recomendados <= 0) {
      cont.innerHTML = `<div class="productividad-nota">✅ Con el equipo actual ya alcanzas ${data.sl_estimado_real_pct}% al ${Math.round(meta*100)}% de meta — no hace falta contratar.</div>`;
      return;
    }
    cont.innerHTML = `
      <div class="productividad-nota tono-rust">
        🎯 Para llegar a ${Math.round(meta*100)}% de servicio necesitarías <strong>${data.asesores_recomendados} asesor(es) más</strong>
        (≈ $${data.costo_estimado_semana_adicional?.toLocaleString('es-CO') || '?'}/semana adicional).${notaMetaDistinta}<br>
        ${data.perfil_sugerido || ""}
      </div>`;
  } catch (e) {
    cont.innerHTML = `<p style="color:var(--rust);">${e.message}</p>`;
  }
}

async function generarHorario() {
  const fecha = document.getElementById("horario-fecha").value;
  const sl = modoUltraProductividad ? "0.85" : "0.95";
  const shrinkage = "0.10";
  const ocupacion = "0.85";
  const proyeccion = document.getElementById("horario-proyeccion").value;
  const factorProyeccion = 1 + (parseFloat(proyeccion) / 100);
  if (!fecha) { alert("Selecciona el lunes de la semana a generar."); return; }

  const semanasBase = _semanasBaseSeleccionadas();
  const modoEspecificas = document.getElementById("btn-modo-especificas").classList.contains("active");
  if (modoEspecificas && !semanasBase) {
    alert("Marca al menos una semana del historial, o cambia a 'Automático'.");
    return;
  }

  const wrap = document.getElementById("horario-tabla-wrap");
  wrap.innerHTML = "<div class='loading-spinner'><span class='spinner'></span> Generando horario...</div>";

  let url = `/horario?fecha_lunes=${fecha}&target_service_level=${sl}&shrinkage=${shrinkage}&max_occupancy=${ocupacion}&factor_proyeccion=${factorProyeccion}`;
  if (semanasBase) url += `&semanas_base=${semanasBase}`;
  const data = await api(url);
  ultimoHorarioGenerado = data;
  horarioGuardadoActual = false;
  ultimoHorarioParametros = { fecha_lunes: fecha, target_service_level: parseFloat(sl), shrinkage: parseFloat(shrinkage),
                              max_occupancy: parseFloat(ocupacion), factor_proyeccion: factorProyeccion, semanas_base: semanasBase };
  const selectMetaContratacion = document.getElementById("horario-meta-contratacion");
  if (selectMetaContratacion && [...selectMetaContratacion.options].some(o => o.value === sl)) {
    selectMetaContratacion.value = sl;
  }
  document.getElementById("horario-guardar-msg").innerHTML = "";
  document.getElementById("horario-contratacion-meta").innerHTML = "";
  actualizarIndicadorGuardado();
  renderHorario(data);
}

function renderHorario(data) {
  const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

  // ---- Resumen de costo ----
  const resumen = document.getElementById("horario-resumen-costo");
  document.getElementById("horario-resultados-wrap").style.display = "block";
  resumen.style.display = "grid";
  resumen.innerHTML = `
    <div class="cost-card ${data.nivel_servicio.sl_estimado_semana_pct >= 85 ? 'ok' : 'alert'}">
      <div class="label">% Contestación estimado (semana)</div>
      <div class="value">${data.nivel_servicio.sl_estimado_semana_pct}%</div>
    </div>
    <div class="cost-card">
      <div class="label">Costo total semana</div>
      <div class="value">$${Math.round(data.costo.total_semana).toLocaleString("es-CO")}</div>
    </div>
    <div class="cost-card">
      <div class="label">Recargo nocturno</div>
      <div class="value">$${Math.round(data.costo.desglose.recargo_nocturno).toLocaleString("es-CO")}</div>
    </div>
    <div class="cost-card">
      <div class="label">Extra dominical</div>
      <div class="value">$${Math.round(data.costo.desglose.extra_por_recargo_dominical).toLocaleString("es-CO")}</div>
    </div>
    <div class="cost-card ${data.alertas.length ? 'alert' : 'ok'}">
      <div class="label">Horas sin cubrir <span style="font-weight:400;">(meta ${Math.round((ultimoHorarioParametros?.target_service_level || 0)*100)}%)</span></div>
      <div class="value">${data.alertas.filter(a => a.includes('faltan')).length}</div>
    </div>
    <div class="cost-card">
      <div class="label">Horas/sem promedio por asesor</div>
      <div class="value">${data.promedio_horas_por_asesor}h</div>
    </div>
  `;

  // ---- % contestación por día ----
  const existente = document.getElementById("horario-por-dia-sl");
  if (existente) existente.remove();
  const porDiaDiv = document.createElement("div");
  porDiaDiv.id = "horario-por-dia-sl";
  porDiaDiv.className = "cost-summary";
  porDiaDiv.style.marginTop = "-6px";
  const DIAS_ORD = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
  porDiaDiv.innerHTML = DIAS_ORD.map(dia => {
    const info = data.nivel_servicio.por_dia[dia];
    const pct = info ? info.sl_estimado_pct : null;
    const clase = pct === null ? '' : (pct >= 85 ? 'ok' : 'alert');
    return `<div class="cost-card ${clase}" style="padding:10px 12px;">
      <div class="label">${dia}</div>
      <div class="value" style="font-size:16px;">${pct !== null ? pct + '%' : '—'}</div>
    </div>`;
  }).join("");
  resumen.after(porDiaDiv);

  // ---- Aviso de festivo ----
  const avisoFestivo = document.getElementById("horario-festivo-aviso");
  const alertasFestivo = data.alertas.filter(a => a.includes("festivo"));
  avisoFestivo.innerHTML = alertasFestivo.length
    ? `<div class="productividad-nota tono-rust">📅 ${alertasFestivo.join("<br>📅 ")}</div>`
    : "";

  // ---- Tabla de turnos ----
  const wrap = document.getElementById("horario-tabla-wrap");
  let html = `<table class="horario-table"><thead><tr><th>Asesor</th>`;
  DIAS.forEach(d => html += `<th>${d}</th>`);
  html += `<th>Horas/sem</th><th>Costo</th></tr></thead><tbody>`;

  const motivos = {
    no_disponible: "No disp.", sin_informacion: "Sin info", libre_no_requerido: "Libre",
    descanso_asignado: "Descanso",
    tope_semanal_alcanzado: "Tope sem.",
    editado_manual: "Libre (manual)",
  };

  for (const [nombre, dias] of Object.entries(data.horario)) {
    html += `<tr><td>${nombre}</td>`;
    DIAS.forEach(dia => {
      const info = dias[dia];
      // El atributo va entre comillas simples porque JSON.stringify() devuelve comillas
      // dobles -- si el atributo también usara comillas dobles, cualquier nombre lo cortaba
      // a la mitad y el clic quedaba roto (aunque el hover por CSS siguiera viéndose bien).
      const nombreJs = JSON.stringify(nombre).replace(/'/g, "&#39;");
      const clickAttr = `onclick='abrirModalEditarTurno(${nombreJs}, ${JSON.stringify(dia)})' title="Clic para editar manualmente este turno"`;
      if (info.tipo === "turno") {
        const texto = info.turnos.map(t => {
          let base = `${String(t.inicio).padStart(2,'0')}-${String(t.fin).padStart(2,'0')}h${t.excepcion ? '*' : ''}`;
          if (t.almuerzo_horas) {
            const af = t.almuerzo_inicio + t.almuerzo_horas;
            base += `<br><span class="almuerzo-tag">🍽 ${String(t.almuerzo_inicio).padStart(2,'0')}-${String(af).padStart(2,'0')}h</span>`;
          }
          return base;
        }).join(" + ");
        html += `<td class="turno-badge turno-editable" ${clickAttr}>${texto}</td>`;
      } else if (info.motivo && info.motivo.startsWith("permiso:")) {
        html += `<td class="libre-badge">${info.motivo.replace('permiso:', '')}</td>`;
      } else {
        html += `<td class="libre-badge turno-editable" ${clickAttr}>${motivos[info.motivo] || info.motivo}</td>`;
      }
    });
    const horas = data.horas_semana[nombre] || 0;
    const costo = data.costo.costo_por_empleado[nombre] || 0;
    html += `<td>${horas}h</td><td>$${Math.round(costo).toLocaleString("es-CO")}</td></tr>`;
  }
  html += `</tbody></table>`;
  wrap.innerHTML = html;

  // ---- Gráfica de cobertura por hora ----
  coberturaActual = data.cobertura;
  document.getElementById("horario-cobertura-seccion").style.display = "block"; // ya visible vía el wrap padre
  const tabsDiv = document.getElementById("horario-dia-tabs");
  tabsDiv.innerHTML = `<span class="disp-toolbar-label">Día:</span>` + DIAS.map((dia, i) =>
    `<button class="chip-btn" id="tab-dia-${i}" onclick="mostrarCoberturaDia('${dia}', ${i})">${dia}</button>`
  ).join("");
  mostrarCoberturaDia(DIAS[0], 0);
}

// ---- Edición manual de un turno ya generado (clic en una celda de la tabla de Horarios) ----
let turnoEditandoNombre = null;
let turnoEditandoDia = null;

function abrirModalEditarTurno(nombre, dia) {
  if (!ultimoHorarioGenerado) return;
  turnoEditandoNombre = nombre;
  turnoEditandoDia = dia;
  document.getElementById("modal-editar-turno-titulo").textContent = `Editar turno -- ${nombre} (${dia})`;
  document.getElementById("editar-turno-error").textContent = "";

  const info = ultimoHorarioGenerado.horario[nombre][dia];
  if (info.tipo === "turno" && info.turnos && info.turnos.length) {
    // Si había varios bloques (turno partido), se precarga el primero -- al guardar, el
    // resto queda reemplazado por este único bloque (ver aviso en el modal).
    const t = info.turnos[0];
    document.getElementById("editar-turno-inicio").value = t.inicio;
    document.getElementById("editar-turno-fin").value = t.fin;
    document.getElementById("editar-turno-almuerzo-inicio").value = t.almuerzo_inicio ?? "";
    document.getElementById("editar-turno-almuerzo-horas").value = t.almuerzo_horas || 0;
  } else {
    document.getElementById("editar-turno-inicio").value = 11;
    document.getElementById("editar-turno-fin").value = 19;
    document.getElementById("editar-turno-almuerzo-inicio").value = "";
    document.getElementById("editar-turno-almuerzo-horas").value = 0;
  }
  abrirModal("modal-editar-turno");
}

async function _aplicarEdicionTurnoYRecalcular(nuevaCelda) {
  ultimoHorarioGenerado.horario[turnoEditandoNombre][turnoEditandoDia] = nuevaCelda;
  cerrarModal("modal-editar-turno");

  const wrap = document.getElementById("horario-tabla-wrap");
  const htmlPrevio = wrap.innerHTML;
  wrap.innerHTML = "<div class='loading-spinner'><span class='spinner'></span> Recalculando...</div>";
  try {
    const data = await api("/horario/recalcular", {
      method: "POST",
      body: JSON.stringify({
        fecha_lunes: ultimoHorarioParametros.fecha_lunes,
        horario: ultimoHorarioGenerado.horario,
        target_service_level: ultimoHorarioParametros.target_service_level,
        shrinkage: ultimoHorarioParametros.shrinkage,
        max_occupancy: ultimoHorarioParametros.max_occupancy,
        factor_proyeccion: ultimoHorarioParametros.factor_proyeccion,
        semanas_base: ultimoHorarioParametros.semanas_base,
      }),
    });
    ultimoHorarioGenerado = data;
    horarioGuardadoActual = false;
    actualizarIndicadorGuardado();
    renderHorario(data);
  } catch (e) {
    wrap.innerHTML = htmlPrevio;
    alert(`No se pudo recalcular el horario con el cambio manual: ${e.message}`);
  }
}

function guardarTurnoManual() {
  const inicio = parseInt(document.getElementById("editar-turno-inicio").value, 10);
  const fin = parseInt(document.getElementById("editar-turno-fin").value, 10);
  const almInicioRaw = document.getElementById("editar-turno-almuerzo-inicio").value;
  const almHoras = parseFloat(document.getElementById("editar-turno-almuerzo-horas").value) || 0;

  if (isNaN(inicio) || isNaN(fin) || fin <= inicio) {
    document.getElementById("editar-turno-error").textContent = "La hora fin debe ser mayor que la hora inicio.";
    return;
  }
  const turno = { inicio, fin, excepcion: true };
  if (almInicioRaw !== "" && almHoras > 0) {
    const almInicio = parseInt(almInicioRaw, 10);
    if (almInicio < inicio || almInicio + almHoras > fin) {
      document.getElementById("editar-turno-error").textContent = "El almuerzo debe quedar dentro del turno.";
      return;
    }
    turno.almuerzo_inicio = almInicio;
    turno.almuerzo_horas = almHoras;
  }
  _aplicarEdicionTurnoYRecalcular({ tipo: "turno", turnos: [turno] });
}

function eliminarTurnoManual() {
  _aplicarEdicionTurnoYRecalcular({ tipo: "libre", motivo: "editado_manual" });
}

let coberturaActual = null;
let chartCoberturaHorario = null;

function mostrarCoberturaDia(dia, indice) {
  document.querySelectorAll("[id^='tab-dia-']").forEach(b => b.classList.remove("chip-btn-active"));
  document.getElementById(`tab-dia-${indice}`)?.classList.add("chip-btn-active");

  const filas = coberturaActual[dia] || [];
  const horas = filas.map(f => `${f.hora}:00`);
  const requeridos = filas.map(f => f.requeridos);
  const programados = filas.map(f => f.programados);
  const slPorHora = filas.map(f => f.sl_estimado_pct);
  const colorProgramados = filas.map(f => f.programados < f.requeridos ? "#B7541D" : "#2F7A52");

  const ctx = document.getElementById("chart-cobertura-horario").getContext("2d");
  if (chartCoberturaHorario) chartCoberturaHorario.destroy();
  chartCoberturaHorario = new Chart(ctx, {
    type: "bar",
    data: {
      labels: horas,
      datasets: [
        { label: "Requeridos (para la meta actual)", data: requeridos, backgroundColor: "#1B2430", order: 2, yAxisID: "y" },
        { label: "Programados", data: programados, backgroundColor: colorProgramados, order: 1, yAxisID: "y" },
        { label: "% de servicio estimado real", data: slPorHora, type: "line", borderColor: "#C8102E",
          backgroundColor: "#C8102E", yAxisID: "y1", order: 0, tension: 0.25, pointRadius: 3 },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { position: "bottom" },
        title: { display: true, text: `Cobertura — ${dia}`, align: "start", color: "#1B2430", font: { size: 13, weight: "bold" } },
        tooltip: {
          callbacks: {
            afterBody: (items) => {
              const i = items[0].dataIndex;
              const sl = slPorHora[i];
              return sl != null ? [`% de servicio estimado real esa hora: ${sl}%`] : [];
            },
          },
        },
      },
      scales: {
        x: { ticks: { font: { size: 10.5 } } },
        y: { beginAtZero: true, title: { display: true, text: "Agentes" } },
        y1: { beginAtZero: false, min: 0, max: 100, position: "right", grid: { drawOnChartArea: false },
              title: { display: true, text: "% de servicio" } },
      },
    },
  });
}

// ---------- BRECHA DE PERSONAL ----------

function inicializarVistaBrecha() {
  const input = document.getElementById("brecha-fecha");
  if (!input.value) input.value = _proximoLunes();
}

async function cargarBrecha() {
  const fecha = document.getElementById("brecha-fecha")?.value || _proximoLunes();
  const shrinkage = document.getElementById("brecha-shrinkage")?.value || "0.10";
  const sl = document.getElementById("brecha-sl")?.value || "0.95";

  const resumen = document.getElementById("brecha-resumen");
  resumen.innerHTML = `<div class="cost-card"><div class="label">Simulando...</div><div class="value">⏳</div></div>`;

  const data = await api(`/brecha-personal?fecha_lunes=${fecha}&shrinkage=${shrinkage}&target_service_level=${sl}`);

  const brechaOk = data.deficit_total_real <= 0;
  resumen.innerHTML = `
    <div class="cost-card ${data.sl_estimado_real_pct >= 85 ? 'ok' : 'alert'}">
      <div class="label">% Contestación real esperado</div>
      <div class="value">${data.sl_estimado_real_pct}%</div>
    </div>
    <div class="cost-card ${brechaOk ? 'ok' : 'alert'}">
      <div class="label">Déficit real total</div>
      <div class="value">${data.deficit_total_real}h</div>
    </div>
    <div class="cost-card ${brechaOk ? 'ok' : 'alert'}">
      <div class="label">Asesores recomendados</div>
      <div class="value">${data.asesores_recomendados}</div>
    </div>
    ${data.costo_estimado_semana_adicional ? `
    <div class="cost-card">
      <div class="label">Costo adicional estimado/semana</div>
      <div class="value">$${data.costo_estimado_semana_adicional.toLocaleString('es-CO')}</div>
    </div>` : ""}
  `;

  const perfilDiv = document.getElementById("brecha-perfil-sugerido");
  perfilDiv.innerHTML = data.perfil_sugerido
    ? `<div class="productividad-nota tono-rust">🎯 <strong>Perfil de contratación sugerido:</strong> ${data.perfil_sugerido}</div>`
    : `<div class="productividad-nota">✅ Con estos parámetros, el equipo actual alcanza a cubrir toda la demanda simulada — no hace falta contratar.</div>`;

  const badgeEstado = { critico: '<span class="badge badge-alerta">Crítico</span>', ajustado: '<span class="badge badge-ajustado">Ajustado</span>', cubierto: '<span class="badge badge-ok">Cubierto</span>' };
  document.getElementById("tabla-brecha-dias").innerHTML = data.detalle_por_dia.map(d => `
    <tr>
      <td><strong>${d.dia}</strong></td>
      <td>${d.requerido}h</td>
      <td>${d.programado_real}h</td>
      <td>${d.pct_cubierto_real}%</td>
      <td>${d.deficit > 0 ? d.deficit + 'h' : '—'}</td>
      <td>${badgeEstado[d.estado]}</td>
    </tr>
  `).join("");

  document.getElementById("tabla-brecha-franjas").innerHTML = data.peores_franjas.length
    ? data.peores_franjas.map(f => `
        <tr>
          <td>${f.dia}</td>
          <td>${f.hora}:00</td>
          <td>${f.deficit} agente(s)</td>
          <td>${f.deficit_relativo_pct}%</td>
        </tr>
      `).join("")
    : `<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">Sin franjas críticas — todo bien cubierto ✓</td></tr>`;
}

// ---------- TARIFAS ----------

async function cargarTarifas() {
  const t = await api("/tarifas");
  document.getElementById("tarifa-normal").value = t.valor_hora_normal;
  document.getElementById("tarifa-dominical").value = t.valor_recargo_dominical;
  document.getElementById("tarifa-nocturno").value = t.valor_recargo_nocturno;
  document.getElementById("tarifa-transporte").value = t.valor_subsidio_transporte_hora;
}

async function descargarPdfSimple(endpoint, nombreArchivo, params = "") {
  const boton = event.target;
  const textoOriginal = boton.textContent;
  boton.textContent = "Generando PDF...";
  boton.disabled = true;
  try {
    const res = await fetch(`${API}${endpoint}${params ? "?" + params : ""}`);
    if (!res.ok) throw new Error("No se pudo generar el PDF");
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = nombreArchivo;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch (e) {
    alert(e.message);
  } finally {
    boton.textContent = textoOriginal;
    boton.disabled = false;
  }
}

function descargarPdfMetricas() {
  descargarPdfSimple("/metricas/pdf", "reporte_metricas.pdf", _filtrosMetricas());
}

function descargarReporteEjecutivo() {
  const params = new URLSearchParams(_filtrosMetricas());
  params.set("fecha_lunes_referencia", _proximoLunes());
  descargarPdfSimple("/reporte-ejecutivo/pdf", "reporte_ejecutivo.pdf", params.toString());
}

async function descargarPdfSimplePost(endpoint, nombreArchivo, body) {
  const boton = event.target;
  const textoOriginal = boton.textContent;
  boton.textContent = "Generando...";
  boton.disabled = true;
  try {
    const res = await fetch(`${API}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      throw new Error(data?.detail || "No se pudo generar el archivo");
    }
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = nombreArchivo;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch (e) {
    alert(e.message);
  } finally {
    boton.textContent = textoOriginal;
    boton.disabled = false;
  }
}

// Arma el body para /horario/pdf y /horario/excel a partir de EXACTAMENTE lo que hay en
// pantalla (ultimoHorarioGenerado) -- así lo que se descarga nunca difiere de lo que la
// persona está viendo (horario guardado del Historial, o con ediciones manuales todavía
// sin guardar). Devuelve null si no hay nada generado para esa fecha en memoria.
function _bodyReporteHorarioExacto(fecha, mostrarCostos) {
  if (!ultimoHorarioGenerado || !ultimoHorarioParametros || ultimoHorarioParametros.fecha_lunes !== fecha) {
    return null;
  }
  return {
    fecha_lunes: fecha,
    horario: ultimoHorarioGenerado.horario,
    target_service_level: ultimoHorarioParametros.target_service_level,
    shrinkage: ultimoHorarioParametros.shrinkage,
    max_occupancy: ultimoHorarioParametros.max_occupancy,
    factor_proyeccion: ultimoHorarioParametros.factor_proyeccion,
    semanas_base: ultimoHorarioParametros.semanas_base,
    mostrar_costos: mostrarCostos,
  };
}

function descargarPdfHorario(mostrarCostos = true) {
  const fecha = document.getElementById("horario-fecha")?.value || _proximoLunes();
  const nombre = `reporte_horario_${fecha}${mostrarCostos ? '' : '_equipo'}.pdf`;
  const body = _bodyReporteHorarioExacto(fecha, mostrarCostos);
  if (body) {
    descargarPdfSimplePost("/horario/pdf", nombre, body);
    return;
  }
  // Respaldo: no hay nada generado en memoria para esta fecha (ej. se llamó directo sin
  // pasar por la pantalla) -- genera de cero con los parámetros actuales.
  const sl = modoUltraProductividad ? "0.85" : "0.95";
  const shrinkage = "0.10";
  const ocupacion = "0.85";
  let params = `fecha_lunes=${fecha}&target_service_level=${sl}&shrinkage=${shrinkage}&max_occupancy=${ocupacion}&mostrar_costos=${mostrarCostos}`;
  const semanasBase = _semanasBaseSeleccionadas();
  if (semanasBase) params += `&semanas_base=${semanasBase}`;
  descargarPdfSimple("/horario/pdf", nombre, params);
}

function descargarExcelHorario(mostrarCostos = true) {
  const fecha = document.getElementById("horario-fecha")?.value || _proximoLunes();
  const nombre = `horario_${fecha}${mostrarCostos ? '' : '_equipo'}.xlsx`;
  const body = _bodyReporteHorarioExacto(fecha, mostrarCostos);
  if (body) {
    descargarPdfSimplePost("/horario/excel", nombre, body);
    return;
  }
  const sl = modoUltraProductividad ? "0.85" : "0.95";
  const shrinkage = "0.10";
  const ocupacion = "0.85";
  let params = `fecha_lunes=${fecha}&target_service_level=${sl}&shrinkage=${shrinkage}&max_occupancy=${ocupacion}&mostrar_costos=${mostrarCostos}`;
  const semanasBase = _semanasBaseSeleccionadas();
  if (semanasBase) params += `&semanas_base=${semanasBase}`;
  descargarPdfSimple("/horario/excel", nombre, params);
}

async function descargarPdfBrecha() {
  const fecha = document.getElementById("brecha-fecha")?.value || _proximoLunes();
  const shrinkage = document.getElementById("brecha-shrinkage")?.value || "0.10";
  const sl = document.getElementById("brecha-sl")?.value || "0.95";
  const boton = event.target;
  const textoOriginal = boton.textContent;
  boton.textContent = "Generando PDF...";
  boton.disabled = true;
  try {
    const res = await fetch(`${API}/brecha-personal/pdf?fecha_lunes=${fecha}&target_service_level=${sl}&shrinkage=${shrinkage}`);
    if (!res.ok) throw new Error("No se pudo generar el PDF");
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `reporte_brecha_personal_${fecha}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
  } catch (e) {
    alert(e.message);
  } finally {
    boton.textContent = textoOriginal;
    boton.disabled = false;
  }
}

async function guardarTarifas() {
  const msg = document.getElementById("tarifas-msg");
  await api("/tarifas", {
    method: "PUT",
    body: JSON.stringify({
      valor_hora_normal: parseFloat(document.getElementById("tarifa-normal").value),
      valor_recargo_dominical: parseFloat(document.getElementById("tarifa-dominical").value),
      valor_recargo_nocturno: parseFloat(document.getElementById("tarifa-nocturno").value),
      valor_subsidio_transporte_hora: parseFloat(document.getElementById("tarifa-transporte").value),
    }),
  });
  msg.textContent = "Tarifas guardadas ✓";
  setTimeout(() => msg.textContent = "", 2500);
}

// ---------- IMPORTAR DATOS ----------

async function _subirArchivo(inputId, endpoint) {
  const input = document.getElementById(inputId);
  if (!input.files.length) {
    alert("Selecciona un archivo primero.");
    return null;
  }
  const formData = new FormData();
  formData.append("file", input.files[0]);

  const res = await fetch(API + endpoint, { method: "POST", body: formData });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.detail || "Error al importar el archivo");
  return data;
}

async function subirDisponibilidad() {
  const div = document.getElementById("resultado-disponibilidad");
  div.innerHTML = "Importando...";
  try {
    const r = await _subirArchivo("file-disponibilidad", "/importar/disponibilidad");
    if (!r) return;
    let html = `<span class="ok">${r.empleados_creados} creados, ${r.empleados_actualizados} actualizados.</span>`;
    if (!r.columna_cedula_encontrada) {
      html += `<br><span class="warn">No se encontró columna de Cédula en el archivo.</span>`;
    }
    if (r.celdas_sin_informacion && r.celdas_sin_informacion.length) {
      html += `<br><span class="warn">${r.celdas_sin_informacion.length} celda(s) sin información (revisar disponibilidad manualmente).</span>`;
    }
    div.innerHTML = html;
  } catch (e) {
    div.innerHTML = `<span class="warn">${e.message}</span>`;
  }
}

async function subirLlamadas() {
  const div = document.getElementById("resultado-llamadas");
  div.innerHTML = "Importando (puede tardar unos segundos)...";
  try {
    const r = await _subirArchivo("file-llamadas", "/importar/llamadas");
    if (!r) return;
    div.innerHTML = `<span class="ok">${r.insertadas_nuevas} llamadas nuevas insertadas.</span>` +
      `<br>${r.ya_existian} ya existían (ignoradas, sin duplicar).` +
      `<br>Histórico total: ${r.rango_total_bd.mn} a ${r.rango_total_bd.mx} (${r.rango_total_bd.c} llamadas).`;
  } catch (e) {
    div.innerHTML = `<span class="warn">${e.message}</span>`;
  }
}

// ---------- ZONA DE PELIGRO: borrar llamadas ----------

async function borrarTodasLasLlamadas() {
  if (!(await confirmarAccion("¿Seguro que quieres borrar TODO el histórico de llamadas? Esta acción no se puede deshacer."))) return;
  if (!(await confirmarAccion("Confirmación final: se borrarán TODAS las llamadas cargadas hasta hoy. ¿Continuar?", { textoBoton: "Sí, borrar todo" }))) return;

  const msg = document.getElementById("danger-zone-msg");
  msg.style.color = "var(--text-muted)";
  msg.textContent = "Borrando...";
  try {
    const r = await api("/llamadas", { method: "DELETE" });
    msg.style.color = "var(--green)";
    msg.textContent = `Listo: se borraron ${r.llamadas_borradas} llamadas. Ya puedes subir el archivo corregido arriba.`;
  } catch (e) {
    msg.style.color = "var(--rust)";
    msg.textContent = e.message;
  }
}

async function borrarRangoLlamadas() {
  const fi = document.getElementById("borrar-fecha-inicio").value;
  const ff = document.getElementById("borrar-fecha-fin").value;
  const msg = document.getElementById("danger-zone-msg");
  if (!fi || !ff) { msg.style.color = "var(--rust)"; msg.textContent = "Selecciona ambas fechas."; return; }
  if (!(await confirmarAccion(`¿Borrar todas las llamadas entre ${fi} y ${ff}? Esta acción no se puede deshacer.`))) return;

  msg.style.color = "var(--text-muted)";
  msg.textContent = "Borrando...";
  try {
    const r = await api(`/llamadas/rango?fecha_inicio=${fi}&fecha_fin=${ff}`, { method: "DELETE" });
    msg.style.color = "var(--green)";
    msg.textContent = `Listo: se borraron ${r.llamadas_borradas} llamadas de ese rango.`;
  } catch (e) {
    msg.style.color = "var(--rust)";
    msg.textContent = e.message;
  }
}

// ---------- MÉTRICAS ----------

let chartTendencia = null;
let metricasCache = null;
let modoTendencia = "contestacion";
let chartPorHora = null;
let chartTendenciaDiaSemana = null;

function _poblarSelectHoras() {
  ["metricas-hora-inicio", "metricas-hora-fin"].forEach(id => {
    const sel = document.getElementById(id);
    if (sel.options.length > 1) return; // ya poblado
    for (let h = 0; h < 24; h++) {
      const opt = document.createElement("option");
      opt.value = h;
      opt.textContent = `${String(h).padStart(2, '0')}:00`;
      sel.appendChild(opt);
    }
  });
}

function _filtrosMetricas() {
  const p = new URLSearchParams();
  const fi = document.getElementById("metricas-fecha-inicio").value;
  const ff = document.getElementById("metricas-fecha-fin").value;
  const hi = document.getElementById("metricas-hora-inicio").value;
  const hf = document.getElementById("metricas-hora-fin").value;
  if (fi) p.set("fecha_inicio", fi);
  if (ff) p.set("fecha_fin", ff);
  if (hi !== "") p.set("hora_inicio", hi);
  if (hf !== "") p.set("hora_fin", hf);
  return p.toString();
}

function limpiarFiltrosMetricas() {
  document.getElementById("metricas-fecha-inicio").value = "";
  document.getElementById("metricas-fecha-fin").value = "";
  document.getElementById("metricas-hora-inicio").value = "";
  document.getElementById("metricas-hora-fin").value = "";
  cargarMetricas();
}

async function cargarMetricas() {
  _poblarSelectHoras();
  const qs = _filtrosMetricas();
  const kpisDiv = document.getElementById("metricas-kpis");
  let m;
  try {
    m = await api(`/metricas${qs ? "?" + qs : ""}`);
  } catch (e) {
    kpisDiv.innerHTML = `<div class="empty-state" style="grid-column:1/-1;">
      No hay llamadas para ese filtro (o todavía no has importado ninguna).<br>
      <a onclick="mostrarVista('importar')">Ir a Importar Datos →</a>
    </div>`;
    document.querySelectorAll(".chart-card canvas").forEach(c => c.style.display = "none");
    document.getElementById("tabla-resumen-dia-semana").innerHTML = "";
    document.getElementById("tabla-desglose-dia-hora").innerHTML = "";
    return;
  }
  document.querySelectorAll(".chart-card canvas").forEach(c => c.style.display = "block");

  // ---- Tabla de promedio por día de la semana ----
  const resumenDia = await api(`/resumen-dia-semana${qs ? "?" + qs : ""}`);
  document.getElementById("tabla-resumen-dia-semana").innerHTML = resumenDia.map(d => `
    <tr>
      <td>${d.dia_semana}</td>
      <td>${d.dias_observados}</td>
      <td><strong>${Math.round(d.contestadas_promedio)}</strong></td>
      <td>${d.contestadas_min} – ${d.contestadas_max}</td>
      <td>${Math.round(d.abandonadas_promedio)}</td>
      <td style="color:${d.pct_caidas_promedio > 10 ? 'var(--rust)' : 'inherit'};">${d.pct_caidas_promedio}%</td>
      <td>${Math.floor(d.tmo_seg_promedio/60)}:${String(Math.round(d.tmo_seg_promedio%60)).padStart(2,'0')}</td>
      <td><strong>${d.agentes_hora_automatico ?? '—'}</strong>h</td>
    </tr>
  `).join("");

  kpisDiv.innerHTML = `
    <div class="cost-card">
      <div class="label">Llamadas totales (${m.dias_con_datos} días)</div>
      <div class="value">${m.total_llamadas.toLocaleString("es-CO")}</div>
    </div>
    <div class="cost-card ${m.pct_contestadas >= 90 ? 'ok' : 'alert'}">
      <div class="label">% Contestadas</div>
      <div class="value">${m.pct_contestadas}%</div>
    </div>
    <div class="cost-card">
      <div class="label">Abandonadas</div>
      <div class="value">${m.abandonadas.toLocaleString("es-CO")}</div>
    </div>
    <div class="cost-card ${(100 - m.pct_contestadas) > 10 ? 'alert' : 'ok'}">
      <div class="label">% Llamadas caídas</div>
      <div class="value">${(100 - m.pct_contestadas).toFixed(1)}%</div>
    </div>
    <div class="cost-card">
      <div class="label">TMO promedio</div>
      <div class="value">${Math.floor(m.tmo_promedio_seg/60)}:${String(Math.round(m.tmo_promedio_seg%60)).padStart(2,'0')}</div>
    </div>
    <div class="cost-card">
      <div class="label">Espera prom. antes de abandonar</div>
      <div class="value">${Math.round(m.espera_promedio_abandono_seg)}s</div>
    </div>
  `;

  // ---- Gráfica de tendencia diaria (contestación o caídas, según el toggle) ----
  metricasCache = m; // se guarda para que el toggle pueda re-dibujar sin volver a pedir datos
  dibujarChartTendencia();

  // ---- Gráfica por hora del día (barras) + línea de % caídas ----
  const ctx2 = document.getElementById("chart-por-hora").getContext("2d");
  if (chartPorHora) chartPorHora.destroy();
  const pctCaidasPorHora = m.por_hora.map(h => {
    const total = h.llamadas_contestadas_prom_dia + h.llamadas_abandonadas_prom_dia;
    return total > 0 ? Math.round((h.llamadas_abandonadas_prom_dia / total) * 1000) / 10 : 0;
  });
  chartPorHora = new Chart(ctx2, {
    data: {
      labels: m.por_hora.map(h => h.hora_del_dia + ":00"),
      datasets: [
        { type: "bar", label: "Contestadas", data: m.por_hora.map(h => h.llamadas_contestadas_prom_dia), backgroundColor: "#2F7A52", yAxisID: "y", order: 2 },
        { type: "bar", label: "Abandonadas", data: m.por_hora.map(h => h.llamadas_abandonadas_prom_dia), backgroundColor: "#B7541D", yAxisID: "y", order: 2 },
        { type: "line", label: "% Caídas", data: pctCaidasPorHora, borderColor: "#C8102E", backgroundColor: "#C8102E", yAxisID: "y1", tension: 0.3, pointRadius: 3, order: 1 },
      ],
    },
    options: {
      responsive: true,
      scales: {
        x: { stacked: true },
        y: { stacked: true, position: "left", title: { display: true, text: "Llamadas" } },
        y1: { position: "right", min: 0, ticks: { callback: v => v + "%" }, grid: { drawOnChartArea: false }, title: { display: true, text: "% Caídas" } },
      },
      plugins: { legend: { position: "bottom" } },
    },
  });

  // ---- Gráfica de tendencia por día de la semana (barras = contestadas, línea = % caídas) ----
  const tendenciaDia = await api(`/tendencia-dia-semana${qs ? "?" + qs : ""}`);
  const ctx3 = document.getElementById("chart-tendencia-dia-semana").getContext("2d");
  if (chartTendenciaDiaSemana) chartTendenciaDiaSemana.destroy();
  const coloresSemanas = ["#9CA3AF", "#C98A2C", "#B7541D", "#2F7A52", "#1B2430", "#6B7280"];
  const diasEjeX = Object.keys(tendenciaDia.por_dia || {});
  const semanasLista = tendenciaDia.semanas || [];
  // Promedio de % caídas por día (across todas las semanas con dato), como línea de referencia
  const pctCaidasPorDia = diasEjeX.map(dia => {
    const valores = (tendenciaDia.por_dia_pct_caidas?.[dia] || []).filter(v => v !== null);
    return valores.length ? Math.round((valores.reduce((a, b) => a + b, 0) / valores.length) * 10) / 10 : null;
  });
  chartTendenciaDiaSemana = new Chart(ctx3, {
    data: {
      labels: diasEjeX,
      datasets: [
        ...semanasLista.map((semana, i) => ({
          type: "bar", label: semana,
          data: Object.values(tendenciaDia.por_dia).map(valores => valores[i]),
          backgroundColor: coloresSemanas[i % coloresSemanas.length], yAxisID: "y", order: 2,
        })),
        {
          type: "line", label: "% Caídas (promedio)", data: pctCaidasPorDia,
          borderColor: "#C8102E", backgroundColor: "#C8102E", yAxisID: "y1",
          tension: 0.3, pointRadius: 3, order: 1,
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        y: { position: "left", title: { display: true, text: "Llamadas contestadas" } },
        y1: { position: "right", min: 0, ticks: { callback: v => v + "%" }, grid: { drawOnChartArea: false }, title: { display: true, text: "% Caídas" } },
      },
      plugins: { legend: { position: "bottom" } },
    },
  });

  // ---- Tabla matriz: franja horaria x día de la semana ----
  const desglose = await api(`/desglose-dia-hora${qs ? "?" + qs : ""}`);
  const DIAS_ORDEN = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
  const horas = [...new Set(desglose.map(d => d.hora_del_dia))].sort((a, b) => a - b);

  const indice = {};
  desglose.forEach(d => { indice[`${d.dia_semana}-${d.hora_del_dia}`] = d; });

  let htmlMatriz = "<thead><tr><th>Franja</th>";
  DIAS_ORDEN.forEach(d => htmlMatriz += `<th>${d}</th>`);
  htmlMatriz += "</tr></thead><tbody>";

  horas.forEach(h => {
    htmlMatriz += `<tr><td><strong>${h}:00</strong></td>`;
    DIAS_ORDEN.forEach(dia => {
      const celda = indice[`${dia}-${h}`];
      if (celda) {
        const tmoMin = Math.floor(celda.tmo_seg_prom / 60);
        const tmoSeg = String(Math.round(celda.tmo_seg_prom % 60)).padStart(2, '0');
        htmlMatriz += `<td>${Math.round(celda.llamadas_contestadas_prom_dia)} <span style="color:var(--text-muted); font-size:11px;">(TMO ${tmoMin}:${tmoSeg} · </span><strong style="color:var(--amber-dark);">${celda.agentes_requeridos} ag.</strong><span style="color:var(--text-muted); font-size:11px;">)</span></td>`;
      } else {
        htmlMatriz += `<td style="color:var(--text-muted);">—</td>`;
      }
    });
    htmlMatriz += "</tr>";
  });
  htmlMatriz += "</tbody>";
  document.getElementById("tabla-desglose-dia-hora").innerHTML = htmlMatriz;

  // ---- Rendimiento por asesor ----
  const rendimiento = await api(`/metricas/agentes${qs ? "?" + qs : ""}`);
  document.getElementById("tabla-rendimiento-agentes").innerHTML = rendimiento.length
    ? rendimiento.map(a => {
        const tmoMin = Math.floor(a.tmo_promedio_seg / 60);
        const tmoSeg = String(Math.round(a.tmo_promedio_seg % 60)).padStart(2, '0');
        const horasTotal = (a.tiempo_total_atencion_seg / 3600).toFixed(1);
        return `<tr>
          <td>${a.agente}</td>
          <td><strong>${a.llamadas_contestadas.toLocaleString('es-CO')}</strong></td>
          <td>${a.promedio_llamadas_por_dia}</td>
          <td>${tmoMin}:${tmoSeg}</td>
          <td>${horasTotal}h</td>
          <td>${a.dias_activos}</td>
        </tr>`;
      }).join("")
    : `<tr><td colspan="6" style="text-align:center; color:var(--text-muted);">Sin datos de agentes para este filtro</td></tr>`;
}

// ---------- TURNOS (plantillas de horario válido) ----------

async function restaurarPlantillasDefault() {
  if (!(await confirmarAccion("¿Borrar TODAS las plantillas actuales y dejar únicamente las 13 estándar del negocio? Esta acción no se puede deshacer.", { textoBoton: "Sí, restaurar" }))) return;
  try {
    const r = await api("/plantillas-turno/restaurar-default", { method: "POST" });
    alert(`Listo: se restauraron ${r.plantillas_creadas} plantillas por defecto.`);
    cargarPlantillas();
  } catch (e) {
    alert(e.message);
  }
}

async function cargarPlantillas() {
  const plantillas = await api("/plantillas-turno");
  const tbody = document.getElementById("tabla-plantillas");
  const aviso = document.getElementById("turnos-aviso-vacio");

  if (!plantillas.length) {
    aviso.style.display = "block";
    tbody.innerHTML = "";
    return;
  }
  aviso.style.display = "none";

  tbody.innerHTML = plantillas.map(p => {
    const dur = p.hora_fin - p.hora_inicio;
    const durEfectiva = dur - (p.duracion_almuerzo_horas || 0);
    const durTexto = p.duracion_almuerzo_horas > 0
      ? `${durEfectiva}h efectivas (${dur}h con ${p.duracion_almuerzo_horas}h almuerzo)`
      : `${dur}h`;
    const diasAbrev = { "Lunes": "Lun", "Martes": "Mar", "Miércoles": "Mié", "Jueves": "Jue",
                         "Viernes": "Vie", "Sábado": "Sáb", "Domingo": "Dom" };
    const diasTexto = p.dias_aplica.map(d => diasAbrev[d] || d).join(", ");
    const badge = p.es_recomendada ? '<span class="badge-recomendada">✨ Sugerida</span>' : "";
    const opacidad = p.activo ? "" : "opacity:0.5;";
    return `<tr style="${opacidad}">
      <td>${p.nombre || "—"}${badge}</td>
      <td><strong>${String(p.hora_inicio).padStart(2,'0')}:00 - ${String(p.hora_fin).padStart(2,'0')}:00</strong></td>
      <td>${durTexto}</td>
      <td style="font-size:12px; color:var(--text-muted);">${diasTexto}</td>
      <td>
        <label class="switch-toggle" title="${p.activo ? 'Activa -- el generador la usa' : 'Inactiva -- el generador la ignora'}">
          <input type="checkbox" ${p.activo ? "checked" : ""} onchange="alternarActivoPlantilla(${p.id}, this.checked)">
          <span class="switch-rail"></span>
        </label>
      </td>
      <td>
        <button class="btn-icon" onclick='editarPlantilla(${JSON.stringify(p).replace(/'/g, "&apos;")})'>Editar</button>
        <button class="btn-icon" onclick="eliminarPlantilla(${p.id})">Eliminar</button>
      </td>
    </tr>`;
  }).join("");
}

async function alternarActivoPlantilla(id, activo) {
  try {
    await api(`/plantillas-turno/${id}`, { method: "PUT", body: JSON.stringify({ activo }) });
    cargarPlantillas();
  } catch (e) {
    alert(e.message);
    cargarPlantillas();
  }
}

async function recomendarPlantillas() {
  const caja = document.getElementById("turnos-resultado-recomendacion");
  caja.style.display = "block";
  caja.innerHTML = `<div class="loading-spinner"><span class="spinner"></span> Analizando dónde queda déficit con las plantillas actuales...</div>`;
  try {
    const fecha = _proximoLunes();
    const r = await api(`/plantillas-turno/recomendar?fecha_lunes=${fecha}&target_service_level=0.95&shrinkage=0.10&max_occupancy=0.85`, { method: "POST" });
    if (!r.plantillas_creadas.length) {
      caja.innerHTML = `<div class="recomendacion-resultado-box" style="background:var(--paper); border-color:var(--border);">
        Con las plantillas y disponibilidad actuales no encontré huecos donde una plantilla nueva ayude
        (o ya existen plantillas que los cubren). El % de servicio estimado para la semana del ${fecha} es ${r.sl_estimado_antes_pct}%.
      </div>`;
    } else {
      const mejora = (r.sl_estimado_despues_pct - r.sl_estimado_antes_pct);
      const colorMejora = mejora > 0.5 ? "var(--green)" : (mejora < -0.5 ? "var(--rust)" : "var(--text-muted)");
      const listaDetalle = r.plantillas_creadas.map(p =>
        `<li><strong>${String(p.hora_inicio).padStart(2,'0')}:00-${String(p.hora_fin).padStart(2,'0')}:00</strong> (${p.dias_aplica.join(", ")}) -- tapa: ${p.detalle_huecos.join("; ")}</li>`
      ).join("");
      caja.innerHTML = `<div class="recomendacion-resultado-box" style="background:var(--warn-bg); border-color:#E9CE9C;">
        <div style="font-weight:700; margin-bottom:6px;">✨ ${r.plantillas_creadas.length} plantilla(s) nueva(s) agregada(s) (activas, marcadas como "Sugerida")</div>
        <div style="margin-bottom:10px;">% de servicio estimado para la semana del ${fecha}:
          <strong>${r.sl_estimado_antes_pct}%</strong> → <strong style="color:${colorMejora};">${r.sl_estimado_despues_pct}%</strong>
          ${Math.abs(mejora) < 0.5 ? ' <span style="color:var(--text-muted); font-weight:400;">(cambio marginal -- el límite real probablemente es cantidad de gente/disponibilidad, no la forma del turno; revisa Brecha de Personal)</span>' : ''}
        </div>
        <ul style="margin:0; padding-left:18px; font-size:12.5px; color:var(--text-muted);">${listaDetalle}</ul>
      </div>`;
    }
    cargarPlantillas();
  } catch (e) {
    caja.innerHTML = `<div class="recomendacion-resultado-box" style="background:#FBE9E1; border-color:#F0CCBB; color:var(--rust);">${e.message}</div>`;
  }
}

function _renderCheckboxesDias(diasSeleccionados = []) {
  const cont = document.getElementById("plantilla-dias-checkboxes");
  cont.innerHTML = DIAS.map(dia => `
    <label class="dia-checkbox-item">
      <input type="checkbox" value="${dia}" ${diasSeleccionados.includes(dia) ? "checked" : ""}>
      ${dia}
    </label>
  `).join("");
}

function abrirModalNuevaPlantilla() {
  document.getElementById("modal-plantilla-titulo").textContent = "Nueva plantilla de turno";
  document.getElementById("plantilla-id").value = "";
  document.getElementById("plantilla-nombre").value = "";
  document.getElementById("plantilla-hora-inicio").value = 11;
  document.getElementById("plantilla-hora-fin").value = 19;
  document.getElementById("plantilla-almuerzo").value = 0;
  document.getElementById("plantilla-error").textContent = "";
  _renderCheckboxesDias(["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]);
  abrirModal("modal-plantilla");
}

function editarPlantilla(p) {
  document.getElementById("modal-plantilla-titulo").textContent = "Editar plantilla de turno";
  document.getElementById("plantilla-id").value = p.id;
  document.getElementById("plantilla-nombre").value = p.nombre || "";
  document.getElementById("plantilla-hora-inicio").value = p.hora_inicio;
  document.getElementById("plantilla-hora-fin").value = p.hora_fin;
  document.getElementById("plantilla-almuerzo").value = p.duracion_almuerzo_horas || 0;
  document.getElementById("plantilla-error").textContent = "";
  _renderCheckboxesDias(p.dias_aplica);
  abrirModal("modal-plantilla");
}

async function guardarPlantilla() {
  const errEl = document.getElementById("plantilla-error");
  const id = document.getElementById("plantilla-id").value;
  const nombre = document.getElementById("plantilla-nombre").value.trim() || null;
  const horaInicio = parseInt(document.getElementById("plantilla-hora-inicio").value);
  const horaFin = parseInt(document.getElementById("plantilla-hora-fin").value);
  const almuerzo = parseFloat(document.getElementById("plantilla-almuerzo").value) || 0;
  const diasAplica = Array.from(document.querySelectorAll("#plantilla-dias-checkboxes input:checked")).map(el => el.value);

  if (horaFin <= horaInicio) { errEl.textContent = "La hora fin debe ser mayor que la hora inicio."; return; }
  if (!diasAplica.length) { errEl.textContent = "Selecciona al menos un día."; return; }

  const payload = { nombre, hora_inicio: horaInicio, hora_fin: horaFin, dias_aplica: diasAplica,
                     duracion_almuerzo_horas: almuerzo };
  try {
    if (id) {
      await api(`/plantillas-turno/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      await api("/plantillas-turno", { method: "POST", body: JSON.stringify(payload) });
    }
    cerrarModal("modal-plantilla");
    cargarPlantillas();
  } catch (e) {
    errEl.textContent = e.message;
  }
}

async function eliminarPlantilla(id) {
  if (!(await confirmarAccion("¿Eliminar esta plantilla de turno?"))) return;
  try {
    await api(`/plantillas-turno/${id}`, { method: "DELETE" });
    cargarPlantillas();
  } catch (e) {
    alert(e.message);
  }
}

// ---------- HISTORIAL DE HORARIOS ----------

async function cargarHistorialHorarios() {
  const tbody = document.getElementById("tabla-historial");
  try {
    const registros = await api("/horarios-generados");
    tbody.innerHTML = registros.length
      ? registros.map(r => {
          const fecha = new Date(r.generado_en);
          const fechaTexto = fecha.toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short" });
          const cumpleTexto = r.cumple_normativa
            ? '<span class="badge badge-ok">OK</span>'
            : '<span class="badge badge-alerta">Revisar</span>';
          return `<tr>
            <td><strong>${r.fecha_lunes}</strong></td>
            <td style="font-size:12px; color:var(--text-muted);">${fechaTexto}</td>
            <td>${r.generado_por}</td>
            <td>${r.sl_estimado_pct}%</td>
            <td>$${Math.round(r.costo_total).toLocaleString('es-CO')}</td>
            <td>${cumpleTexto}</td>
            <td>
              <button class="btn-icon" onclick="verHorarioHistorial('${r.fecha_lunes}')">Ver</button>
              <button class="btn-icon" onclick="compararHorarioReal('${r.fecha_lunes}')">Comparar con real</button>
              <button class="btn-icon" onclick="eliminarHorarioHistorial('${r.fecha_lunes}')">Eliminar</button>
            </td>
          </tr>`;
        }).join("")
      : `<tr><td colspan="7" style="text-align:center; color:var(--text-muted);">Todavía no has guardado ningún horario -- genera uno en Horarios y dale "Guardar en el Historial"</td></tr>`;
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--text-muted);">${e.message}</td></tr>`;
  }
  document.getElementById("historial-comparacion").innerHTML = "";
}

async function verHorarioHistorial(fechaLunes) {
  try {
    const registro = await api(`/horarios-generados/${fechaLunes}`);
    mostrarVista("horarios");
    document.getElementById("horario-fecha").value = fechaLunes;
    modoUltraProductividad = registro.parametros.target_service_level <= 0.85;
    document.getElementById("ultra-productividad-estado").textContent = modoUltraProductividad ? "Encendido" : "Apagado";
    document.getElementById("btn-ultra-productividad").classList.toggle("activo", modoUltraProductividad);
    // Importante: sincronizar el estado en memoria con lo que se está mostrando -- si no,
    // "Descargar PDF/Excel" o editar un turno a mano después de ver un horario del
    // Historial seguiría operando sobre lo último generado en esta sesión (o nada), no
    // sobre lo que realmente está en pantalla.
    ultimoHorarioGenerado = registro.resultado;
    ultimoHorarioParametros = { ...registro.parametros, fecha_lunes: fechaLunes };
    horarioGuardadoActual = true;
    actualizarIndicadorGuardado();
    renderHorario(registro.resultado);
    document.getElementById("nota-historial")?.remove();
    document.getElementById("horario-resultados-wrap").insertAdjacentHTML("beforebegin",
      `<div class="productividad-nota tono-info" id="nota-historial">
        📋 Mostrando el horario guardado el ${new Date(registro.generado_en).toLocaleString('es-CO')} por ${registro.generado_por} (meta ${Math.round(registro.parametros.target_service_level*100)}%).
        Si generas uno nuevo para esta semana, reemplazará este en el historial.
      </div>`);
  } catch (e) {
    alert(e.message);
  }
}

async function eliminarHorarioHistorial(fechaLunes) {
  if (!(await confirmarAccion(`¿Eliminar del historial el horario de la semana del ${fechaLunes}?`))) return;
  try {
    await api(`/horarios-generados/${fechaLunes}`, { method: "DELETE" });
    cargarHistorialHorarios();
  } catch (e) {
    alert(e.message);
  }
}

// ---------- COMPARADOR DE ESCENARIOS ----------

const OPCIONES_SL = [[0.80,"80%"],[0.85,"85%"],[0.90,"90%"],[0.95,"95%"],[0.98,"98%"],[1.0,"100%"]];
const OPCIONES_SHRINKAGE = [[0.10,"10%"],[0.15,"15%"],[0.20,"20%"],[0.25,"25%"],[0.30,"30%"]];
const OPCIONES_PROYECCION = [[0,"Normal (0%)"],[5,"+5%"],[10,"+10%"],[20,"+20%"],[30,"+30%"]];

function inicializarComparador() {
  const fechaInput = document.getElementById("comparar-fecha");
  if (!fechaInput.value) fechaInput.value = _proximoLunes();

  const grid = document.getElementById("escenarios-grid");
  if (grid.children.length) return; // ya está armado, no reconstruir

  const defaults = [
    { sl: 0.95, shrink: 0.10, proy: 0 },
    { sl: 0.85, shrink: 0.10, proy: 0 },
    { sl: 0.95, shrink: 0.10, proy: 10 },
  ];

  grid.innerHTML = defaults.map((d, i) => `
    <div class="escenario-card">
      <h4>Escenario ${i + 1}</h4>
      <label>Meta de servicio</label>
      <select id="esc-${i}-sl">
        ${OPCIONES_SL.map(([v,t]) => `<option value="${v}" ${v===d.sl?'selected':''}>${t}</option>`).join("")}
      </select>
      <label>Shrinkage</label>
      <select id="esc-${i}-shrink">
        ${OPCIONES_SHRINKAGE.map(([v,t]) => `<option value="${v}" ${v===d.shrink?'selected':''}>${t}</option>`).join("")}
      </select>
      <label>Proyección</label>
      <select id="esc-${i}-proy">
        ${OPCIONES_PROYECCION.map(([v,t]) => `<option value="${v}" ${v===d.proy?'selected':''}>${t}</option>`).join("")}
      </select>
    </div>
  `).join("");
}

async function compararEscenarios() {
  const fecha = document.getElementById("comparar-fecha").value;
  if (!fecha) { alert("Selecciona la semana a comparar."); return; }

  const cont = document.getElementById("comparar-resultado");
  cont.innerHTML = "<div class='loading-spinner'><span class='spinner'></span> Corriendo los 3 escenarios...</div>";

  const resultados = [];
  for (let i = 0; i < 3; i++) {
    const sl = document.getElementById(`esc-${i}-sl`).value;
    const shrink = document.getElementById(`esc-${i}-shrink`).value;
    const proy = document.getElementById(`esc-${i}-proy`).value;
    const factorProy = 1 + (parseFloat(proy) / 100);
    try {
      const data = await api(`/horario?fecha_lunes=${fecha}&target_service_level=${sl}&shrinkage=${shrink}&factor_proyeccion=${factorProy}`);
      resultados.push({ ok: true, sl, shrink, proy, data });
    } catch (e) {
      resultados.push({ ok: false, sl, shrink, proy, error: e.message });
    }
  }

  renderComparacion(resultados);
}

function renderComparacion(resultados) {
  const cont = document.getElementById("comparar-resultado");

  const valoresSL = resultados.map(r => r.ok ? r.data.nivel_servicio.sl_estimado_semana_pct : null);
  const valoresCosto = resultados.map(r => r.ok ? r.data.costo.total_semana : null);
  const maxSL = Math.max(...valoresSL.filter(v => v !== null));
  const minCosto = Math.min(...valoresCosto.filter(v => v !== null));

  const filaConfig = (label, getter) => `<tr><td>${label}</td>${resultados.map(r => `<td>${r.ok ? getter(r) : '—'}</td>`).join("")}</tr>`;

  const html = `
    <h2 class="section-title">Resultado de la comparación</h2>
    <table class="data-table tabla-comparacion">
      <thead><tr><th></th>${resultados.map((r,i) => `<th>Escenario ${i+1}</th>`).join("")}</tr></thead>
      <tbody>
        ${filaConfig("Meta de servicio", r => `${Math.round(r.sl*100)}%`)}
        ${filaConfig("Shrinkage", r => `${Math.round(r.shrink*100)}%`)}
        ${filaConfig("Proyección", r => `+${r.proy}%`)}
        <tr>
          <td><strong>% Contestación estimado</strong></td>
          ${resultados.map(r => r.ok
            ? `<td class="${r.data.nivel_servicio.sl_estimado_semana_pct === maxSL ? 'mejor' : ''}">${r.data.nivel_servicio.sl_estimado_semana_pct}%</td>`
            : `<td class="peor">Error</td>`).join("")}
        </tr>
        <tr>
          <td><strong>Costo total semana</strong></td>
          ${resultados.map(r => r.ok
            ? `<td class="${r.data.costo.total_semana === minCosto ? 'mejor' : ''}">$${Math.round(r.data.costo.total_semana).toLocaleString('es-CO')}</td>`
            : `<td>—</td>`).join("")}
        </tr>
        <tr>
          <td><strong>Horas-persona</strong></td>
          ${resultados.map(r => r.ok ? `<td>${Math.round(Object.values(r.data.horas_semana).reduce((a,b)=>a+b,0))}h</td>` : `<td>—</td>`).join("")}
        </tr>
        <tr>
          <td><strong>Cumplimiento normativo</strong></td>
          ${resultados.map(r => r.ok
            ? `<td>${r.data.cumplimiento.resumen.cumple ? '<span class="badge badge-ok">OK</span>' : `<span class="badge badge-alerta">${r.data.cumplimiento.resumen.total_violaciones} violación(es)</span>`}</td>`
            : `<td>—</td>`).join("")}
        </tr>
        <tr>
          <td><strong>Alertas de cobertura</strong></td>
          ${resultados.map(r => r.ok ? `<td>${r.data.alertas.filter(a => a.includes('faltan')).length}</td>` : `<td>—</td>`).join("")}
        </tr>
      </tbody>
    </table>
    <p style="font-size:11.5px; color:var(--text-muted); margin-top:10px;">
      En verde: el mejor valor de esa fila entre los 3 escenarios.
    </p>
  `;
  cont.innerHTML = html;
}

// ---------- NOTIFICACIONES ----------

let notificacionesCache = [];

async function cargarNotificaciones() {
  try {
    notificacionesCache = await api("/notificaciones");
    const badge = document.getElementById("notif-badge");
    const descartadas = _obtenerDescartadas();
    const alertas = notificacionesCache.filter(n => n.nivel === "alerta" && !descartadas.includes(_claveNotificacion(n))).length;
    const boton = document.querySelector(".notif-bell-fab");
    if (alertas > 0) {
      badge.textContent = alertas;
      badge.style.display = "inline-block";
      boton?.classList.add("con-alertas");
    } else {
      badge.style.display = "none";
      boton?.classList.remove("con-alertas");
    }
    _renderPanelNotificaciones();
  } catch (e) {
    // silencioso -- no interrumpir el uso normal si esto falla
  }
}

// Mapea el tipo de alerta al módulo donde se puede resolver, para el botón "Ver"
const VISTA_POR_TIPO_NOTIF = {
  disponibilidad: "disponibilidad", personal: "personal",
  cumplimiento: "historial", brecha: "brecha",
};

function _claveNotificacion(n) {
  return `${n.tipo}::${n.mensaje}`;
}

function _obtenerDescartadas() {
  try {
    return JSON.parse(localStorage.getItem("notif_descartadas") || "[]");
  } catch (e) {
    return [];
  }
}

function descartarNotificacion(clave) {
  const descartadas = _obtenerDescartadas();
  if (!descartadas.includes(clave)) descartadas.push(clave);
  localStorage.setItem("notif_descartadas", JSON.stringify(descartadas));
  _renderPanelNotificaciones();
}

function _renderPanelNotificaciones() {
  const lista = document.getElementById("notif-panel-lista");
  const descartadas = _obtenerDescartadas();
  const visibles = notificacionesCache.filter(n => !descartadas.includes(_claveNotificacion(n)));
  lista.innerHTML = visibles.length
    ? visibles.map(n => {
        const clave = _claveNotificacion(n);
        const vista = VISTA_POR_TIPO_NOTIF[n.tipo];
        return `
          <div class="notif-item ${n.nivel}">
            <div>${n.mensaje}</div>
            <div class="notif-item-acciones">
              ${vista ? `<button class="notif-item-btn" onclick="mostrarVista('${vista}'); toggleNotificaciones();">Ver</button>` : ""}
              <button class="notif-item-btn" onclick="descartarNotificacion('${clave.replace(/'/g, "\\'")}')">Descartar</button>
            </div>
          </div>`;
      }).join("")
    : `<div class="notif-vacio">Todo en orden — sin alertas pendientes ✓</div>`;
}

function toggleNotificaciones() {
  const panel = document.getElementById("notif-panel");
  panel.style.display = panel.style.display === "none" ? "block" : "none";
}

document.addEventListener("click", (e) => {
  const panel = document.getElementById("notif-panel");
  const boton = document.querySelector(".notif-bell-fab");
  if (panel && panel.style.display === "block" && !panel.contains(e.target) && e.target !== boton && !boton.contains(e.target)) {
    panel.style.display = "none";
  }
});

// ---------- CONFIGURACIÓN GENERAL (solo superadmin) ----------

async function cargarConfiguracion() {
  try {
    const cfg = await api("/configuracion");
    document.getElementById("cfg-horario-inicio").value = cfg.horario_operativo_inicio;
    document.getElementById("cfg-horario-fin").value = cfg.horario_operativo_fin;
    document.getElementById("cfg-domingo-max").value = cfg.domingo_max_horas;
    document.getElementById("cfg-max-turnos-dia").value = cfg.max_turnos_por_dia;
    document.getElementById("cfg-duracion-preferida").value = cfg.duracion_preferida_max;
    document.getElementById("cfg-dias-prioridad").value = cfg.n_dias_prioridad_maxima;
    document.getElementById("cfg-factor-decaimiento").value = cfg.factor_decaimiento;
    document.getElementById("cfg-dias-consecutivos").value = cfg.max_dias_consecutivos;
    document.getElementById("cfg-descanso-minimo").value = cfg.descanso_minimo_horas;
    document.getElementById("cfg-descanso-domingo").checked = !!cfg.permitir_descanso_domingo;
    document.getElementById("cfg-sl-default").value = cfg.target_service_level_default;
    document.getElementById("cfg-shrinkage-default").value = cfg.shrinkage_default;
    document.getElementById("cfg-ocupacion-default").value = cfg.max_occupancy_default;
    document.getElementById("cfg-target-answer").value = cfg.target_answer_seconds;
    document.getElementById("cfg-semanas-rotacion").value = cfg.semanas_rotacion_historial;
    document.getElementById("cfg-margen-seguridad").value = cfg.margen_seguridad_agentes;
    document.getElementById("cfg-piso-minimo").value = cfg.fraccion_piso_minimo;
    document.getElementById("cfg-recargo-nocturno-hora").value = cfg.hora_inicio_recargo_nocturno;
    document.getElementById("cfg-sesion-horas").value = cfg.session_max_age_horas;
    document.getElementById("cfg-horas-min-dia-nuevo").value = cfg.horas_min_dia_default;
    document.getElementById("cfg-horas-max-dia-nuevo").value = cfg.horas_max_dia_default;
    document.getElementById("cfg-horas-min-semana-nuevo").value = cfg.horas_min_semana_default;
    document.getElementById("cfg-horas-max-semana-nuevo").value = cfg.horas_max_semana_default;
  } catch (e) {
    document.getElementById("config-guardado-msg").textContent = e.message;
  }
}

function marcarConfigSinGuardar() {
  document.getElementById("config-actions-sticky")?.classList.add("sin-guardar");
  const msg = document.getElementById("config-guardado-msg");
  if (msg) { msg.textContent = ""; }
}

async function guardarConfiguracion() {
  const msg = document.getElementById("config-guardado-msg");
  const payload = {
    horario_operativo_inicio: parseInt(document.getElementById("cfg-horario-inicio").value),
    horario_operativo_fin: parseInt(document.getElementById("cfg-horario-fin").value),
    domingo_max_horas: parseInt(document.getElementById("cfg-domingo-max").value),
    max_turnos_por_dia: parseInt(document.getElementById("cfg-max-turnos-dia").value),
    duracion_preferida_max: parseInt(document.getElementById("cfg-duracion-preferida").value),
    n_dias_prioridad_maxima: parseInt(document.getElementById("cfg-dias-prioridad").value),
    factor_decaimiento: parseFloat(document.getElementById("cfg-factor-decaimiento").value),
    max_dias_consecutivos: parseInt(document.getElementById("cfg-dias-consecutivos").value),
    descanso_minimo_horas: parseInt(document.getElementById("cfg-descanso-minimo").value),
    permitir_descanso_domingo: document.getElementById("cfg-descanso-domingo").checked,
    target_service_level_default: parseFloat(document.getElementById("cfg-sl-default").value),
    shrinkage_default: parseFloat(document.getElementById("cfg-shrinkage-default").value),
    max_occupancy_default: parseFloat(document.getElementById("cfg-ocupacion-default").value),
    target_answer_seconds: parseInt(document.getElementById("cfg-target-answer").value),
    semanas_rotacion_historial: parseInt(document.getElementById("cfg-semanas-rotacion").value),
    margen_seguridad_agentes: parseInt(document.getElementById("cfg-margen-seguridad").value),
    fraccion_piso_minimo: parseFloat(document.getElementById("cfg-piso-minimo").value),
    hora_inicio_recargo_nocturno: parseInt(document.getElementById("cfg-recargo-nocturno-hora").value),
    session_max_age_horas: parseInt(document.getElementById("cfg-sesion-horas").value),
    horas_min_dia_default: parseFloat(document.getElementById("cfg-horas-min-dia-nuevo").value),
    horas_max_dia_default: parseFloat(document.getElementById("cfg-horas-max-dia-nuevo").value),
    horas_min_semana_default: parseFloat(document.getElementById("cfg-horas-min-semana-nuevo").value),
    horas_max_semana_default: parseFloat(document.getElementById("cfg-horas-max-semana-nuevo").value),
  };

  if (payload.horario_operativo_fin <= payload.horario_operativo_inicio) {
    msg.style.color = "var(--rust)";
    msg.textContent = "La hora de fin debe ser mayor que la de inicio.";
    return;
  }

  try {
    await api("/configuracion", { method: "PUT", body: JSON.stringify(payload) });
    msg.style.color = "var(--green)";
    msg.textContent = "Guardado ✓ — aplica desde el próximo horario que generes.";
    document.getElementById("config-actions-sticky")?.classList.remove("sin-guardar");
  } catch (e) {
    msg.style.color = "var(--rust)";
    msg.textContent = e.message;
  }
}

// ---------- Toggle % Contestación / % Caídas en la tendencia diaria ----------

function cambiarModoTendencia(modo) {
  modoTendencia = modo;
  document.getElementById("btn-modo-contestacion").classList.toggle("active", modo === "contestacion");
  document.getElementById("btn-modo-caidas").classList.toggle("active", modo === "caidas");
  dibujarChartTendencia();
}

function dibujarChartTendencia() {
  if (!metricasCache) return;
  const m = metricasCache;
  const ctx1 = document.getElementById("chart-tendencia").getContext("2d");
  if (chartTendencia) chartTendencia.destroy();

  const esCaidas = modoTendencia === "caidas";
  const valores = m.serie_diaria.map(d => esCaidas ? Math.round((100 - d.pct_contestadas) * 10) / 10 : d.pct_contestadas);

  chartTendencia = new Chart(ctx1, {
    type: "line",
    data: {
      labels: m.serie_diaria.map(d => d.fecha.slice(5)),
      datasets: [{
        label: esCaidas ? "% Caídas" : "% Contestadas",
        data: valores,
        borderColor: esCaidas ? "#C8102E" : "#C98A2C",
        backgroundColor: esCaidas ? "rgba(200,16,30,0.1)" : "rgba(201,138,44,0.1)",
        tension: 0.25, fill: true, pointRadius: 2,
      }],
    },
    options: {
      responsive: true,
      scales: { y: esCaidas ? { min: 0, ticks: { callback: v => v + "%" } } : { min: 80, max: 100, ticks: { callback: v => v + "%" } } },
      plugins: { legend: { display: false } },
    },
  });
}

// ---------- MI CUENTA: perfil (foto + nombre a mostrar) ----------

let fotoPerfilPendiente = undefined; // undefined = sin cambios, null = quitar, string = nueva foto

function _iniciales(nombre) {
  return (nombre || "?").trim().slice(0, 2).toUpperCase();
}

async function cargarMiCuenta() {
  fotoPerfilPendiente = undefined;
  try {
    const yo = await api("/me");
    usuarioActual.foto_perfil = yo.foto_perfil;
    usuarioActual.nombre_display = yo.nombre_display;
  } catch (e) { /* usar lo que ya había en usuarioActual */ }

  document.getElementById("perfil-nombre-display").value = usuarioActual.nombre_display || "";
  _renderFotoPerfil(usuarioActual.foto_perfil);
}

function _renderFotoPerfil(foto) {
  const img = document.getElementById("perfil-foto-preview");
  const placeholder = document.getElementById("perfil-foto-placeholder");
  if (foto) {
    img.src = foto;
    img.style.display = "block";
    placeholder.style.display = "none";
  } else {
    img.style.display = "none";
    placeholder.style.display = "flex";
    placeholder.textContent = _iniciales(usuarioActual.nombre_display || usuarioActual.username);
  }
}

function onSeleccionarFotoPerfil(event) {
  const file = event.target.files[0];
  if (!file) return;
  const msg = document.getElementById("perfil-msg");
  if (!file.type.startsWith("image/")) { msg.textContent = "Elige un archivo de imagen."; return; }

  const reader = new FileReader();
  reader.onload = (e) => {
    const img = new Image();
    img.onload = () => {
      // Se reduce a máx 200x200 y se comprime a JPEG antes de guardar, para no inflar la BD
      const tam = 200;
      const canvas = document.createElement("canvas");
      canvas.width = tam;
      canvas.height = tam;
      const ctx = canvas.getContext("2d");
      const lado = Math.min(img.width, img.height);
      const sx = (img.width - lado) / 2, sy = (img.height - lado) / 2;
      ctx.drawImage(img, sx, sy, lado, lado, 0, 0, tam, tam);
      const dataUrl = canvas.toDataURL("image/jpeg", 0.8);
      fotoPerfilPendiente = dataUrl;
      _renderFotoPerfil(dataUrl);
      msg.style.color = "var(--text-muted)";
      msg.textContent = "Foto lista -- dale click a 'Guardar perfil' para confirmar.";
    };
    img.src = e.target.result;
  };
  reader.readAsDataURL(file);
}

function quitarFotoPerfil() {
  fotoPerfilPendiente = null;
  _renderFotoPerfil(null);
  document.getElementById("perfil-msg").textContent = "Se quitará la foto al guardar.";
}

async function guardarPerfil() {
  const msg = document.getElementById("perfil-msg");
  const nombreDisplay = document.getElementById("perfil-nombre-display").value.trim() || null;
  const payload = { nombre_display: nombreDisplay };
  if (fotoPerfilPendiente !== undefined) payload.foto_perfil = fotoPerfilPendiente;

  try {
    await api("/mi-perfil", { method: "PUT", body: JSON.stringify(payload) });
    usuarioActual.nombre_display = nombreDisplay;
    if (fotoPerfilPendiente !== undefined) usuarioActual.foto_perfil = fotoPerfilPendiente;
    fotoPerfilPendiente = undefined;
    msg.style.color = "var(--green)";
    msg.textContent = "Perfil actualizado ✓";
  } catch (e) {
    msg.style.color = "var(--rust)";
    msg.textContent = e.message;
  }
}

// ---------- PERSONAL: selección múltiple (para habilitar horas extra masivo) ----------

let empleadosSeleccionados = new Set();

function toggleSeleccionEmpleado(id, marcado) {
  if (marcado) empleadosSeleccionados.add(id);
  else empleadosSeleccionados.delete(id);
  const todas = document.querySelectorAll(".chk-empleado");
  document.getElementById("chk-empleados-todos").checked =
    todas.length > 0 && empleadosSeleccionados.size === todas.length;
  actualizarBarraSeleccionEmpleados();
}

function toggleSeleccionTodosEmpleados(checkboxTodos) {
  document.querySelectorAll(".chk-empleado").forEach(chk => {
    chk.checked = checkboxTodos.checked;
    const id = parseInt(chk.dataset.id, 10);
    if (checkboxTodos.checked) empleadosSeleccionados.add(id);
    else empleadosSeleccionados.delete(id);
  });
  actualizarBarraSeleccionEmpleados();
}

function deseleccionarTodosEmpleados() {
  empleadosSeleccionados.clear();
  document.querySelectorAll(".chk-empleado").forEach(chk => chk.checked = false);
  const todos = document.getElementById("chk-empleados-todos");
  if (todos) todos.checked = false;
  actualizarBarraSeleccionEmpleados();
}

function actualizarBarraSeleccionEmpleados() {
  const toolbar = document.getElementById("personal-bulk-toolbar");
  const n = empleadosSeleccionados.size;
  toolbar.style.display = n > 0 ? "flex" : "none";
  document.getElementById("personal-bulk-count").textContent =
    n === 1 ? "1 asesor seleccionado" : `${n} asesores seleccionados`;
}

// ---------- PERSONAL: horas extra (individual o masivo por selección) ----------

let horasExtraEmpleadoId = null;   // modo individual: id del asesor
let horasExtraModoMasivo = false;  // modo masivo: aplica a empleadosSeleccionados

function abrirModalHorasExtra(id, nombre, permiteActual, horasActuales) {
  horasExtraModoMasivo = false;
  horasExtraEmpleadoId = id;
  document.getElementById("horas-extra-titulo").textContent = `Horas extra — ${nombre}`;
  document.getElementById("horas-extra-activar-label").textContent = "Permitir horas extra a este asesor";
  document.getElementById("horas-extra-activar").checked = !!permiteActual;
  document.getElementById("horas-extra-cantidad").value = horasActuales > 0 ? horasActuales : 8;
  document.getElementById("horas-extra-error").textContent = "";
  onToggleHorasExtra();
  abrirModal("modal-horas-extra");
}

function abrirModalHorasExtraMasivo() {
  if (empleadosSeleccionados.size === 0) return;
  horasExtraModoMasivo = true;
  const n = empleadosSeleccionados.size;
  document.getElementById("horas-extra-titulo").textContent =
    `Horas extra — ${n} asesor${n === 1 ? "" : "es"} seleccionado${n === 1 ? "" : "s"}`;
  document.getElementById("horas-extra-activar-label").textContent =
    "Permitir horas extra a todos los seleccionados";
  document.getElementById("horas-extra-activar").checked = true;
  document.getElementById("horas-extra-cantidad").value = 8;
  document.getElementById("horas-extra-error").textContent = "";
  onToggleHorasExtra();
  abrirModal("modal-horas-extra");
}

function onToggleHorasExtra() {
  document.getElementById("horas-extra-cantidad-wrap").style.display =
    document.getElementById("horas-extra-activar").checked ? "block" : "none";
}

async function guardarHorasExtra() {
  const errEl = document.getElementById("horas-extra-error");
  const permite = document.getElementById("horas-extra-activar").checked;
  const cantidad = parseFloat(document.getElementById("horas-extra-cantidad").value);

  if (permite && (!cantidad || cantidad <= 0)) {
    errEl.textContent = "Define cuántas horas extra por semana (mayor que 0).";
    return;
  }

  try {
    if (horasExtraModoMasivo) {
      const resp = await api(`/empleados/horas-extra/masivo`, {
        method: "PUT",
        body: JSON.stringify({
          empleado_ids: [...empleadosSeleccionados],
          permite_horas_extra: permite,
          max_horas_extra_semana: permite ? cantidad : 0,
        }),
      });
      cerrarModal("modal-horas-extra");
      deseleccionarTodosEmpleados();
      cargarEmpleados();
    } else {
      await api(`/empleados/${horasExtraEmpleadoId}/horas-extra`, {
        method: "PUT",
        body: JSON.stringify({
          permite_horas_extra: permite,
          max_horas_extra_semana: permite ? cantidad : 0,
        }),
      });
      cerrarModal("modal-horas-extra");
      cargarEmpleados();
    }
  } catch (e) {
    errEl.textContent = e.message;
  }
}

// ---------- Guardar horario en Historial (explícito, ya no automático) ----------

async function guardarHorarioEnHistorial() {
  const msg = document.getElementById("horario-guardar-msg");
  if (!ultimoHorarioGenerado || !ultimoHorarioParametros) {
    msg.innerHTML = `<p style="color:var(--rust);">Primero genera un horario.</p>`;
    return;
  }
  try {
    await api("/horarios-generados", {
      method: "POST",
      body: JSON.stringify({
        fecha_lunes: ultimoHorarioParametros.fecha_lunes,
        parametros: ultimoHorarioParametros,
        resultado: ultimoHorarioGenerado,
      }),
    });
    msg.innerHTML = `<p style="color:var(--green); font-size:13px;">Guardado ✓ — podrás compararlo con lo real desde la pestaña Historial cuando esa semana ya haya pasado.</p>`;
    horarioGuardadoActual = true;
    actualizarIndicadorGuardado();
  } catch (e) {
    msg.innerHTML = `<p style="color:var(--rust); font-size:13px;">${e.message}</p>`;
  }
}

// ---------- Comparar horario guardado vs. lo que pasó realmente ----------

async function compararHorarioReal(fechaLunes) {
  const cont = document.getElementById("historial-comparacion");
  cont.innerHTML = "<div class='loading-spinner'><span class='spinner'></span> Comparando contra las llamadas reales...</div>";
  try {
    const c = await api(`/horarios-generados/${fechaLunes}/comparacion`);
    const signo = c.diferencia_sl_puntos >= 0 ? "+" : "";
    cont.innerHTML = `
      <h2 class="section-title">Planeado vs. real -- semana del ${c.fecha_lunes}</h2>
      <div class="cost-summary">
        <div class="cost-card"><div class="label">% Contestación planeado</div><div class="value">${c.sl_planeado}%</div></div>
        <div class="cost-card ${Math.abs(c.diferencia_sl_puntos) <= 5 ? 'ok' : 'alert'}"><div class="label">% Contestación real</div><div class="value">${c.sl_real}%</div></div>
        <div class="cost-card"><div class="label">Diferencia</div><div class="value">${signo}${c.diferencia_sl_puntos} pts</div></div>
        <div class="cost-card"><div class="label">Llamadas reales totales</div><div class="value">${c.llamadas_reales_totales.toLocaleString('es-CO')}</div></div>
      </div>

      <table class="data-table" style="margin-top:16px;">
        <thead><tr><th>Día</th><th>Requerido planeado</th><th>Programado</th><th>Llamadas reales</th></tr></thead>
        <tbody>
          ${c.por_dia.map(d => `<tr><td>${d.dia}</td><td>${d.requerido_planeado}h</td><td>${d.programado}h</td><td>${d.llamadas_reales.toLocaleString('es-CO')}</td></tr>`).join("")}
        </tbody>
      </table>

      <h2 class="section-title">💡 Sugerencias (ninguna se aplica sola -- tú decides)</h2>
      ${c.sugerencias.map(s => `
        <div class="productividad-nota ${s.tipo === 'ok' ? '' : 'tono-warn'}">
          ${s.mensaje}
        </div>
      `).join("")}
    `;
  } catch (e) {
    cont.innerHTML = `<div class="productividad-nota tono-rust">${e.message}</div>`;
  }
}
