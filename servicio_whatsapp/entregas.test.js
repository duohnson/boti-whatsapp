const prueba = require('node:test');
const verificar = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { entregarUnaVez } = require('./entregas');

async function preparar(t) {
    const carpeta = await fs.mkdtemp(path.join(os.tmpdir(), 'boti-entregas-'));
    t.after(() => fs.rm(carpeta, {recursive:true, force:true}));
    return {carpeta, sesion:randomUUID(), datos:{id_envio:randomUUID(), destino:'50611111111', texto:'hola'}};
}

prueba('un reintento confirmado no vuelve a enviar aunque se lea desde disco', async t => {
    const {carpeta,sesion,datos} = await preparar(t);
    let envios = 0;
    const enviar = async () => { envios++; };
    verificar.equal((await entregarUnaVez(carpeta,sesion,datos,enviar)).estado,'enviado');
    verificar.equal((await entregarUnaVez(carpeta,sesion,datos,enviar)).estado,'enviado');
    verificar.equal(envios,1);
});

prueba('un fallo durante el envio queda incierto y no se repite', async t => {
    const {carpeta,sesion,datos} = await preparar(t);
    let envios = 0;
    const enviar = async () => { envios++; throw new Error('respuesta perdida'); };
    verificar.equal((await entregarUnaVez(carpeta,sesion,datos,enviar)).estado,'incierto');
    verificar.equal((await entregarUnaVez(carpeta,sesion,datos,enviar)).estado,'incierto');
    verificar.equal(envios,1);
});

prueba('un pdf pendiente puede reintentarse sin repetir el texto', async t => {
    const {carpeta,sesion,datos} = await preparar(t);
    datos.opcion_pdf = 1;
    let textos = 0, archivos = 0;
    const enviar = async () => { textos++; };
    const primero = await entregarUnaVez(carpeta,sesion,datos,enviar,async () => {throw new Error('pdf temporalmente no disponible');});
    verificar.equal(primero.estado,'fallido');
    const segundo = await entregarUnaVez(carpeta,sesion,datos,enviar,async () => async () => {archivos++;});
    verificar.equal(segundo.estado,'enviado');
    verificar.equal(textos,1);
    verificar.equal(archivos,1);
});

prueba('un mismo identificador no permite cambiar el contenido', async t => {
    const {carpeta,sesion,datos} = await preparar(t);
    await entregarUnaVez(carpeta,sesion,datos,async () => {});
    await verificar.rejects(entregarUnaVez(carpeta,sesion,{...datos,texto:'diferente'},async () => {}), /otro mensaje/);
});

prueba('dos solicitudes simultaneas solo envian una vez', async t => {
    const {carpeta,sesion,datos} = await preparar(t);
    let envios = 0;
    const enviar = async () => {envios++;};
    await Promise.all([entregarUnaVez(carpeta,sesion,datos,enviar), entregarUnaVez(carpeta,sesion,datos,enviar)]);
    verificar.equal(envios,1);
});

prueba('un bloqueo dejado por un reinicio no reenvia a ciegas', async t => {
    const {carpeta,sesion,datos} = await preparar(t);
    await fs.writeFile(path.join(carpeta,`${sesion}-${datos.id_envio}.json.lock`),'');
    let envios = 0;
    verificar.equal((await entregarUnaVez(carpeta,sesion,datos,async () => {envios++;})).estado,'incierto');
    verificar.equal(envios,0);
});
