'use strict';

async function resolverDestinoParaEnvio(cliente, destino) {
    const valor = String(destino || '').trim();
    if (!valor) return '';

    const jid = /^\+?\d{7,20}$/.test(valor)
        ? `${valor.replace(/\D/g, '')}@c.us`
        : valor;
    if (!jid.endsWith('@lid') && !jid.endsWith('@c.us')) return '';

    const [contacto] = await cliente.getContactLidAndPhone([jid]);
    if (contacto?.pn) return contacto.pn;
    if (jid.endsWith('@c.us')) return jid;
    throw new Error(`WhatsApp no pudo resolver el LID ${jid} a un número de teléfono`);
}

module.exports = { resolverDestinoParaEnvio };