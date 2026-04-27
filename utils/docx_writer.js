/**
 * DOCX generation utility using the Node.js `docx` package.
 * Called as a subprocess by the Writer Agent.
 *
 * Usage: node utils/docx_writer.js <input_json_path> <output_docx_path>
 * Input JSON schema: { type: "resume"|"cover_letter", content: {...} }
 */
const { Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, BorderStyle } = require('docx')
const fs = require('fs')

async function main() {
  const [, , inputPath, outputPath] = process.argv
  if (!inputPath || !outputPath) {
    console.error('Usage: node docx_writer.js <input.json> <output.docx>')
    process.exit(1)
  }

  const input = JSON.parse(fs.readFileSync(inputPath, 'utf8'))

  let doc
  switch (input.type) {
    case 'resume':
      doc = buildResume(input.content)
      break
    case 'cover_letter':
      doc = buildCoverLetter(input.content)
      break
    default:
      throw new Error(`Unknown document type: ${input.type}`)
  }

  const buffer = await Packer.toBuffer(doc)
  fs.writeFileSync(outputPath, buffer)
  console.log(`Written: ${outputPath}`)
}

// ── Resume ────────────────────────────────────────────────────────────────────

function buildResume(content) {
  const children = []

  // Name (large heading)
  children.push(new Paragraph({
    children: [new TextRun({ text: content.name || '', bold: true, size: 32 })],
    alignment: AlignmentType.CENTER,
    spacing: { after: 80 },
  }))

  // Contact line
  if (content.contact) {
    children.push(new Paragraph({
      children: [new TextRun({ text: content.contact, size: 20, color: '555555' })],
      alignment: AlignmentType.CENTER,
      spacing: { after: 200 },
    }))
  }

  // Summary
  if (content.summary) {
    children.push(sectionHeading('SUMMARY'))
    children.push(dividerParagraph())
    children.push(new Paragraph({
      children: [new TextRun({ text: content.summary, size: 20 })],
      spacing: { after: 200 },
    }))
  }

  // Experience
  if (content.experience && content.experience.length > 0) {
    children.push(sectionHeading('EXPERIENCE'))
    children.push(dividerParagraph())

    for (const role of content.experience) {
      // Role title + company
      children.push(new Paragraph({
        children: [
          new TextRun({ text: role.title || '', bold: true, size: 22 }),
          new TextRun({ text: `  |  ${role.company || ''}`, size: 22 }),
          new TextRun({ text: `  ${role.dates || ''}`, size: 20, color: '666666' }),
        ],
        spacing: { before: 120, after: 60 },
      }))

      // Bullets
      for (const bullet of (role.bullets || [])) {
        children.push(new Paragraph({
          children: [new TextRun({ text: bullet, size: 20 })],
          bullet: { level: 0 },
          spacing: { after: 40 },
        }))
      }
    }
    children.push(spacerParagraph())
  }

  // Education
  if (content.education && content.education.length > 0) {
    children.push(sectionHeading('EDUCATION'))
    children.push(dividerParagraph())

    for (const edu of content.education) {
      children.push(new Paragraph({
        children: [
          new TextRun({ text: edu.degree || '', bold: true, size: 22 }),
          new TextRun({ text: `  —  ${edu.school || ''}`, size: 20 }),
          new TextRun({ text: `  ${edu.year || ''}`, size: 20, color: '666666' }),
        ],
        spacing: { after: 80 },
      }))
    }
    children.push(spacerParagraph())
  }

  // Skills
  if (content.skills && content.skills.length > 0) {
    children.push(sectionHeading('SKILLS'))
    children.push(dividerParagraph())
    children.push(new Paragraph({
      children: [new TextRun({ text: content.skills.join('  •  '), size: 20 })],
      spacing: { after: 80 },
    }))
  }

  return new Document({
    sections: [{
      properties: {
        page: {
          margin: { top: 720, right: 864, bottom: 720, left: 864 },
        },
      },
      children,
    }],
  })
}

// ── Cover Letter ──────────────────────────────────────────────────────────────

function buildCoverLetter(content) {
  const children = []
  const paragraphs = content.paragraphs || []

  // Date
  children.push(new Paragraph({
    children: [new TextRun({
      text: new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' }),
      size: 20,
    })],
    spacing: { after: 240 },
  }))

  // Body paragraphs
  for (const para of paragraphs) {
    children.push(new Paragraph({
      children: [new TextRun({ text: para, size: 20 })],
      spacing: { after: 200 },
    }))
  }

  // Closing
  children.push(new Paragraph({
    children: [new TextRun({ text: content.closing || 'Sincerely,', size: 20 })],
    spacing: { before: 240, after: 480 },
  }))

  // Signature line
  children.push(new Paragraph({
    children: [new TextRun({ text: content.name || '', bold: true, size: 20 })],
  }))

  return new Document({
    sections: [{
      properties: {
        page: { margin: { top: 1080, right: 1080, bottom: 1080, left: 1080 } },
      },
      children,
    }],
  })
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function sectionHeading(text) {
  return new Paragraph({
    children: [new TextRun({ text, bold: true, size: 22, allCaps: true })],
    spacing: { before: 160, after: 40 },
  })
}

function dividerParagraph() {
  return new Paragraph({
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: '999999' } },
    spacing: { after: 100 },
  })
}

function spacerParagraph() {
  return new Paragraph({ children: [], spacing: { after: 80 } })
}

main().catch(err => {
  console.error(err.message)
  process.exit(1)
})
