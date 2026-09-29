const prueba = require('node:test');
const verificar = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const { EventEmitter } = require('node:events');

function prepararServicio(notificacionPendiente = false) {
    const avisos = [];
    const creados = [];
    class ClientePrueba extends EventEmitter {
        constructor(opciones) { super(); this.opciones = opciones; creados.push(this); }
        async initialize() {}
        async destroy() { this.destruido = true; }
        async logout() {}
        async requestPairingCode(telefono) { this.telefono = telefono; this.emit('code', 'ABCD1234'); }
        async cancelPairingCode() { this.emit('qr', 'nuevo-qr'); }
    }
    const servicio = vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'servidor.js'), 'utf8') + '\n;({crearSesion, desconectarSesion, clientes})', {
        require(nombre) {
            if (nombre === 'whatsapp-web.js') return { Client: ClientePrueba, LocalAuth: class {}, MessageMedia: class {} };
            if (nombre === 'qrcode') return { toDataURL: async valor => `data:image/png;base64,${Buffer.from(valor).toString('base64')}` };
            if (nombre === 'node:http') return {createServer: () => ({listen() {}, close() {}})};
            if (nombre === 'node:fs/promises') return {rm: async () => {}};
            return require(nombre);
        },
        __dirname, Buffer, URL, AbortSignal, setTimeout,
        console: {log() {}, warn() {}, error() {}},
        process: {env: {WHATSAPP_INTERNAL_SECRET:'prueba'}, loadEnvFile() {}, on() {}},
        fetch: async (ruta, opciones) => {
            avisos.push(JSON.parse(opciones.body));
            if (notificacionPendiente) return new Promise(() => {});
            return {ok:true, json:async () => ({estado:'actualizado'})};
        },
    });
    return {servicio, avisos, creados};
}

const terminarEventos = () => new Promise(resolver => setImmediate(resolver));

prueba('el qr se envia a django y se recupera al reintentar sin crear otro cliente', async () => {
    const {servicio, avisos, creados} = prepararServicio();
    const cliente = await servicio.crearSesion('prueba');
    cliente.emit('qr', 'contenido-qr');
    await terminarEventos();
    verificar.equal(avisos.at(-1).estado, 'esperando_qr');
    const codigo = avisos.at(-1).codigo_qr;
    await servicio.crearSesion('prueba');
    verificar.equal(creados.length, 1);
    verificar.equal(avisos.at(-1).codigo_qr, codigo);
});

prueba('el codigo manual se inicia con el telefono y se comunica a django', async () => {
    const {servicio, avisos, creados} = prepararServicio();
    const cliente = await servicio.crearSesion('prueba', '50688888888');
    verificar.equal(creados[0].opciones.pairWithPhoneNumber.phoneNumber, '50688888888');
    cliente.emit('code', 'ABCD1234');
    await terminarEventos();
    verificar.equal(avisos.at(-1).codigo_manual, 'ABCD1234');
    verificar.equal(avisos.at(-1).estado, 'esperando_codigo');
});

prueba('se puede pasar de qr a codigo manual usando el mismo cliente', async () => {
    const {servicio, avisos, creados} = prepararServicio();
    await servicio.crearSesion('prueba');
    await servicio.crearSesion('prueba', '50688888888');
    verificar.equal(creados.length, 1);
    verificar.equal(avisos.at(-1).estado, 'esperando_codigo');
});

prueba('un evento tardio no elimina la sesion nueva', async () => {
    const {servicio} = prepararServicio();
    const anterior = await servicio.crearSesion('prueba');
    anterior.emit('auth_failure', 'error');
    await terminarEventos();
    const nueva = await servicio.crearSesion('prueba');
    anterior.emit('disconnected', 'evento tardio');
    verificar.equal(servicio.clientes.get('prueba'), nueva);
});

prueba('al desconectar se elimina el cliente y se avisa a django', async () => {
    const {servicio, avisos} = prepararServicio();
    await servicio.crearSesion('prueba');
    await servicio.desconectarSesion('prueba');
    verificar.equal(servicio.clientes.size, 0);
    verificar.equal(avisos.at(-1).estado, 'desconectado');
});

prueba('las notificaciones de estado no bloquean las solicitudes de django', async () => {
    const {servicio} = prepararServicio(true);
    await servicio.crearSesion('prueba');
    const resultado = await Promise.race([
        servicio.crearSesion('prueba').then(() => 'completo'),
        new Promise(resolver => setTimeout(() => resolver('agotado'), 200))
    ]);
    verificar.equal(resultado, 'completo');
});
