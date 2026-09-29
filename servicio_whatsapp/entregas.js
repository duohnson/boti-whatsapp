const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash } = require('node:crypto');

async function entregarUnaVez(carpeta, sesion, datos, enviarTexto, enviarPdf) {
    if (!/^[0-9a-f-]{36}$/i.test(datos.id_envio || '')) throw new Error('Falta un identificador de entrega válido');
    await fs.mkdir(carpeta, { recursive: true, mode: 0o700 });
    const archivo = path.join(carpeta, `${sesion}-${datos.id_envio}.json`);
    const bloqueo = `${archivo}.lock`;
    const huella = createHash('sha256').update(JSON.stringify([datos.destino_chat || datos.destino, datos.texto, datos.opcion_pdf || null, datos.pdf_base64 || null])).digest('hex');
    let registro = { huella, estado: 'preparado' };
    try { registro = JSON.parse(await fs.readFile(archivo, 'utf8')); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (registro.huella !== huella) throw new Error('El identificador pertenece a otro mensaje');
    if (registro.estado === 'enviado') return { estado: 'enviado' };
    let candado;
    try { candado = await fs.open(bloqueo, 'wx', 0o600); }
    catch (error) {
        if (error.code === 'EEXIST') return { estado: 'incierto' };
        throw error;
    }
    async function guardar(estado) {
        registro.estado = estado;
        await fs.writeFile(`${archivo}.tmp`, JSON.stringify(registro), { mode: 0o600 });
        await fs.rename(`${archivo}.tmp`, archivo);
    }
    try {
        try { registro = JSON.parse(await fs.readFile(archivo, 'utf8')); }
        catch(error) { if(error.code !== 'ENOENT') throw error; }
        if(registro.huella !== huella) throw new Error('El identificador pertenece a otro mensaje');
        if(registro.estado === 'enviado') return {estado:'enviado'};
        // si se interrumpio el envio no repito una entrega que pudo completarse
        if (['enviando_texto', 'enviando_pdf'].includes(registro.estado)) return { estado: 'incierto' };
        if (registro.estado === 'preparado') {
            await guardar('enviando_texto');
            await enviarTexto();
            await guardar('texto_enviado');
        }
        if (datos.opcion_pdf && registro.estado === 'texto_enviado') {
            const enviar = await enviarPdf();
            await guardar('enviando_pdf');
            await enviar();
        }
        await guardar('enviado');
        return { estado: 'enviado' };
    } catch (error) {
        console.error(`Falló la entrega ${datos.id_envio}: ${error.message}`);
        return { estado: ['enviando_texto', 'enviando_pdf'].includes(registro.estado) ? 'incierto' : 'fallido' };
    } finally {
        await candado.close();
        await fs.rm(bloqueo, { force: true });
    }
}

module.exports = { entregarUnaVez };
