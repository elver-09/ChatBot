module.exports = {
    env: {
        browser: true,
        commonjs: true,
        es2021: true,
    },
    overrides: [
        {
            env: {
                node: true,
            },
            files: ['*.js'],
            parserOptions: {
                sourceType: 'module',
            },
        },
    ],
    parserOptions: {
        ecmaVersion: 'latest',
    },
    plugins: ['bot-whatsapp'],
    extends: ['plugin:bot-whatsapp/recommended'],
};

