"""
Deterministic benchmark documents for the evaluation datasets.

Each dataset in eval/*.json references one of these via its top-level
"document" key. Content is embedded as code (not files) so the documents
are rebuilt identically on every run and the datasets' expected facts and
citation ranges stay in sync.

  soil_lab        3-page PDF  — soil-moisture sensor calibration lab report
  electronics_labs  DOCX      — digital electronics lab report (Lab 04/05/06),
                              built from one paragraph per block so block
                              ranges in golden_dataset.json are predictable:
                              block N is the Nth paragraph below.
"""

import io
from pathlib import Path

import fitz
from docx import Document as DocxDocument

SOIL_LAB_FILENAME = "RAG_Benchmark_Lab_Report_v1.pdf"

SOIL_LAB_PAGES = [
    # Page 1 — Abstract & setup
    "Soil Moisture Sensor Calibration Lab Report. Abstract: This report "
    "documents the calibration of the capacitive soil moisture sensor "
    "revision 2.1. Thirty soil samples were prepared at controlled moisture "
    "levels and measured under laboratory conditions held at 22 degrees "
    "Celsius. The goal was a linear mapping from raw ADC counts to "
    "volumetric water content.",
    # Page 2 — Methodology
    "Methodology: The sensor was calibrated against three reference points: "
    "oven-dry air defining the zero percent reading, a distilled water bath "
    "defining the saturated reading, and a midpoint slurry prepared at half "
    "saturation. Readings were logged every five minutes for a total of 72 "
    "hours using a 12-bit ADC. Each of the thirty samples was measured in "
    "triplicate and averaged to suppress electrical noise.",
    # Page 3 — Results & limitations
    "Results: The calibration produced a linear fit with an R-squared value "
    "of 0.987 across the full moisture range. The mean absolute error of "
    "the calibrated sensor was 2.3 percentage points of volumetric water "
    "content. Firmware version 1.4 applied the new coefficients. Limitation "
    "section: temperature drift above 35 degrees Celsius was not "
    "characterized in this experiment and remains planned future work.",
]

ELECTRONICS_LABS_FILENAME = "RAG_Golden_Electronics_Labs_v2.docx"

# One paragraph per block. golden_dataset.json citation ranges refer to
# these block numbers (1-based, in order).
ELECTRONICS_LABS_PARAGRAPHS = [
    # Block 1 — title
    "Digital Electronics Laboratory Report: Multiplexer, Amplifier, and "
    "Counter Circuits.",
    # Block 2 — abstract
    "Abstract: This report covers three laboratory experiments conducted "
    "during the spring semester: a 4-to-1 multiplexer in Lab 04, an "
    "inverting operational amplifier in Lab 05, and a 4-bit synchronous "
    "counter in Lab 06. All circuits were assembled on solderless "
    "breadboards and verified with a mixed-signal oscilloscope.",
    # Block 3 — equipment
    "Equipment: Measurements used a Rigol DS1104Z oscilloscope, a Rigol "
    "DP832 power supply set to 5 volts, and a Fluke 87V digital multimeter.",
    # Block 4 — Lab 04
    "Lab 04: The 4-to-1 multiplexer was implemented with the 74HC153 "
    "integrated circuit.",
    # Block 5 — Lab 04 function
    "The primary function of the multiplexer is to select one of four data "
    "inputs and route the selected input to a single output line under the "
    "control of two select lines, S1 and S0.",
    # Block 6 — Lab 04 verification
    "The verification approach for the multiplexer was an exhaustive truth "
    "table test: the table was verified for all sixteen select-and-data "
    "combinations, and propagation delay from select transition to stable "
    "output measured 14 nanoseconds typical.",
    # Block 7 — Lab 05 circuit
    "Lab 05: The inverting amplifier was built around a TL072 operational "
    "amplifier with an input resistor of 10 kilo-ohms and a feedback "
    "resistor of 100 kilo-ohms.",
    # Block 8 — Lab 05 gain
    "The measured voltage gain was -9.8, within 2 percent of the ideal -10 "
    "predicted by the ratio of feedback to input resistance.",
    # Block 9 — Lab 05 bandwidth
    "The measured bandwidth at the -3 decibel point was 48 kilohertz, "
    "limited by the gain-bandwidth product of the TL072 at the chosen "
    "noise gain.",
    # Block 10 — Lab 06 circuit
    "Lab 06: The 4-bit synchronous counter used the 74LS163 integrated "
    "circuit clocked at 1 kilohertz.",
    # Block 11 — Lab 06 behavior
    "The counter advanced through all sixteen states from 0000 to 1111 "
    "without skipped or stuck states, and the ripple carry output enabled "
    "correct cascading behavior.",
    # Block 12 — Lab 06 fault finding
    "The fault condition observed in the Lab 06 counter concerned the "
    "clear input: a fault appeared when the clear line was asserted for "
    "fewer than 20 nanoseconds, confirming the datasheet minimum pulse "
    "width requirement.",
    # Block 13 — results summary
    "Results summary: all three circuits met their design targets. The "
    "multiplexer propagation delay, the amplifier gain error, and the "
    "counter maximum clock rate all fell within the tolerances stated in "
    "the course specification.",
    # Block 14 — limitations
    "Limitations: breadboard contact resistance introduced variation of up "
    "to 0.4 percent in the amplifier measurements, and the counter test "
    "used only room-temperature conditions.",
    # Block 15 — future work
    "Future work: repeat the amplifier characterization on a printed "
    "circuit board, extend counter testing across the industrial "
    "temperature range, and replace the manual oscilloscope readings with "
    "an automated data-logging script.",
]

DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _build_soil_lab_pdf() -> bytes:
    with fitz.open() as pdf:
        for text in SOIL_LAB_PAGES:
            page = pdf.new_page()

            # insert_text writes a single line; wrap to keep paragraphs on
            # the page and extractable as contiguous text.
            words = text.split()
            lines = []
            current = ""

            for word in words:
                if len(current) + len(word) + 1 > 90:
                    lines.append(current)
                    current = word
                else:
                    current = f"{current} {word}".strip()
            lines.append(current)

            for index, line in enumerate(lines):
                page.insert_text((72, 90 + index * 16), line)

        return pdf.tobytes()


def _build_electronics_labs_docx() -> bytes:
    document = DocxDocument()

    for paragraph in ELECTRONICS_LABS_PARAGRAPHS:
        document.add_paragraph(paragraph)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


DOCUMENT_REGISTRY = {
    "soil_lab": {
        "filename": SOIL_LAB_FILENAME,
        "content_type": "application/pdf",
        "builder": _build_soil_lab_pdf,
    },
    "electronics_labs": {
        "filename": ELECTRONICS_LABS_FILENAME,
        "content_type": DOCX_CONTENT_TYPE,
        "builder": _build_electronics_labs_docx,
    },
}


def build_document_bytes(document_key: str) -> tuple[str, bytes, str]:
    """
    Build a benchmark document for upload. Returns (filename, bytes, content_type).
    """

    entry = DOCUMENT_REGISTRY.get(document_key)

    if entry is None:
        raise ValueError(
            f"Unknown benchmark document {document_key!r}; "
            f"expected one of {sorted(DOCUMENT_REGISTRY)}"
        )

    return entry["filename"], entry["builder"](), entry["content_type"]
