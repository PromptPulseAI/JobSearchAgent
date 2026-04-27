/**
 * DOCX generation utility using the Node.js `docx` package.
 * Called as a subprocess by the Writer Agent.
 * Full implementation: Commit 7
 *
 * Usage: node utils/docx_writer.js <input_json_path> <output_docx_path>
 * Input JSON schema: { type: "resume"|"cover_letter", content: {...} }
 */
const { Document, Packer, Paragraph, TextRun, HeadingLevel } = require('docx')
const fs = require('fs')
const path = require('path')

async function main() {
  const [, , inputPath, outputPath] = process.argv
  if (!inputPath || !outputPath) {
    console.error('Usage: node docx_writer.js <input.json> <output.docx>')
    process.exit(1)
  }

  const input = JSON.parse(fs.readFileSync(inputPath, 'utf8'))

  // TODO(Commit 7): Full implementation
  //   switch (input.type) {
  //     case 'resume': return generateResume(input.content, outputPath)
  //     case 'cover_letter': return generateCoverLetter(input.content, outputPath)
  //     default: throw new Error(`Unknown document type: ${input.type}`)
  //   }

  // Placeholder: write a minimal stub document so the pipeline doesn't crash
  const doc = new Document({
    sections: [{
      children: [
        new Paragraph({
          text: `[STUB] ${input.type || 'document'} — not yet implemented`,
          heading: HeadingLevel.HEADING_1,
        }),
      ],
    }],
  })

  const buffer = await Packer.toBuffer(doc)
  fs.writeFileSync(outputPath, buffer)
  console.log(`Written: ${outputPath}`)
}

main().catch(err => {
  console.error(err.message)
  process.exit(1)
})
