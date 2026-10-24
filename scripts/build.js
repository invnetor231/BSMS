
const fs = require("fs");
const path = require("path");

const root = process.cwd();
const source = path.join(root, "index.html");
const outputDir = path.join(root, "dist");
const destination = path.join(outputDir, "index.html");

if (!fs.existsSync(source)) {
  throw new Error("O arquivo index.html precisa estar na raiz do repositorio.");
}

fs.mkdirSync(outputDir, { recursive: true });
fs.copyFileSync(source, destination);

console.log("BSMS: index.html copiado para dist com sucesso.");
