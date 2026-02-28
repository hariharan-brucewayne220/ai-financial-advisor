"""
Document Parser Service

Extracts text from various file formats (PDF, CSV, Excel, TXT).
Each format has different parsing strategy to preserve structure.
"""

import logging
import io
from typing import Tuple

logger = logging.getLogger(__name__)


class DocumentParser:
    """Parse various document formats into text."""

    @staticmethod
    async def parse(file_path: str, file_type: str) -> str:
        """
        Parse document and extract text.

        Args:
            file_path: Path to file (local or S3)
            file_type: Type of file (pdf, csv, xlsx, txt)

        Returns:
            Extracted text content
        """
        if file_type.lower() == "pdf":
            return await DocumentParser._parse_pdf(file_path)
        elif file_type.lower() in ["csv", "xlsx"]:
            return await DocumentParser._parse_spreadsheet(file_path, file_type)
        elif file_type.lower() == "txt":
            return await DocumentParser._parse_text(file_path)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")

    @staticmethod
    async def _parse_pdf(file_path: str) -> str:
        """
        Parse PDF using pdfplumber.

        **Why pdfplumber?**
        - Preserves table structure (important for financial docs)
        - Extracts text with formatting info
        - Can extract tables directly
        """
        try:
            import pdfplumber

            text_parts = []
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    # Extract text
                    text = page.extract_text()
                    if text:
                        text_parts.append(f"--- Page {page_num} ---\n{text}")

                    # Extract tables if present
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            table_text = "\n".join([" | ".join(str(cell) for cell in row) for row in table])
                            text_parts.append(f"\n[TABLE]\n{table_text}\n[/TABLE]")

            return "\n\n".join(text_parts)
        except ImportError:
            raise ImportError("pdfplumber not installed. pip install pdfplumber")
        except Exception as e:
            logger.error(f"Error parsing PDF {file_path}: {e}")
            raise

    @staticmethod
    async def _parse_spreadsheet(file_path: str, file_type: str) -> str:
        """
        Parse CSV or Excel files.

        **Why pandas?**
        - Handles both CSV and Excel consistently
        - Preserves column headers
        - Handles different encodings
        """
        try:
            import pandas as pd

            if file_type.lower() == "csv":
                df = pd.read_csv(file_path)
            elif file_type.lower() == "xlsx":
                # Excel can have multiple sheets
                xls = pd.ExcelFile(file_path)
                text_parts = []
                for sheet_name in xls.sheet_names:
                    df = pd.read_excel(file_path, sheet_name=sheet_name)
                    text_parts.append(f"=== Sheet: {sheet_name} ===\n{df.to_string()}")
                return "\n\n".join(text_parts)
            else:
                raise ValueError(f"Unknown spreadsheet type: {file_type}")

            return df.to_string()
        except ImportError:
            raise ImportError("pandas not installed. pip install pandas openpyxl")
        except Exception as e:
            logger.error(f"Error parsing spreadsheet {file_path}: {e}")
            raise

    @staticmethod
    async def _parse_text(file_path: str) -> str:
        """Parse plain text file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            # Try with different encoding
            with open(file_path, "r", encoding="latin-1") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error parsing text file {file_path}: {e}")
            raise
