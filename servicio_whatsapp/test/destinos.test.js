'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { resolverDestinoParaEnvio } = require('../destinos');

test('resuelve un LID mediante la correspondencia LID/teléfono de WhatsApp', async () => {
    const cliente = {
        async getContactLidAndPhone(ids) {
            assert.deepEqual(ids, ['75488714322075@lid']);
            return [{ lid: '75488714322075@lid', pn: '50688887777@c.us' }];
        },
    };

    assert.equal(
        await resolverDestinoParaEnvio(cliente, '75488714322075@lid'),
        '50688887777@c.us',
    );
});

test('no inventa un número si WhatsApp no puede resolver el LID', async () => {
    const cliente = {
        async getContactLidAndPhone() {
            return [{}];
        },
    };

    await assert.rejects(
        resolverDestinoParaEnvio(cliente, '75488714322075@lid'),
        /no pudo resolver el LID/,
    );
});

test('mantiene compatibilidad con JID telefónico sin LID asociado', async () => {
    const cliente = {
        async getContactLidAndPhone() {
            return [{}];
        },
    };

    assert.equal(
        await resolverDestinoParaEnvio(cliente, '50688887777@c.us'),
        '50688887777@c.us',
    );
});