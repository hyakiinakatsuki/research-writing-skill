#!/usr/bin/env python3
"""
Scholar Search - Multi-database academic literature search tool.

Supported databases:
  - pubmed: PubMed (biomedical)
  - crossref: CrossRef (all disciplines)
  - semanticscholar: Semantic Scholar (AI-enhanced)
  - arxiv: arXiv (preprints, CS/physics/math)
  - openalex: OpenAlex (free, all disciplines)
  - cnki: CNKI (Chinese academic literature, 中国知网)
  - baidu_xueshu: Baidu Scholar (百度学术, Chinese academic aggregator)

Supported output formats:
  - json: JSON format (default)
  - bibtex: BibTeX format for LaTeX
  - ris: RIS format for EndNote/Zotero
  - apa: APA citation style
  - mla: MLA citation style
  - chicago: Chicago citation style
  - vancouver: Vancouver citation style

Usage:
  python scholar_search.py "deep learning" --sources crossref --year 2020-2024 --limit 20
  python scholar_search.py "transformer attention" --format bibtex --output refs.bib
  python scholar_search.py "quantum computing" --format apa --limit 5
"""

import argparse
import json
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════
# Citation Formatting Functions
# ═══════════════════════════════════════════════════════════════════════

def clean_text(text: str) -> str:
    """Remove characters that break citation formats."""
    if not text:
        return ""
    text = re.sub(r"[{}\[\]\\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def generate_cite_key(paper: dict) -> str:
    """Generate a BibTeX citation key from paper data."""
    authors = paper.get("authors", [])
    if authors:
        first_author = authors[0] if isinstance(authors[0], str) else str(authors[0])
        # Extract last name
        parts = first_author.split()
        last_name = parts[-1] if parts else "unknown"
        last_name = re.sub(r"[^a-zA-Z]", "", last_name).lower()
    else:
        last_name = "unknown"
    year = str(paper.get("year") or "XXXX")
    return f"{last_name}{year}"


def normalize_paper(data: dict) -> dict:
    """Normalize paper dict for citation formatting."""
    authors = data.get("authors", [])
    if isinstance(authors, list):
        authors_str = " and ".join(authors)
    else:
        authors_str = str(authors)

    return {
        "title": data.get("title") or "Unknown",
        "authors_str": authors_str,
        "journal": data.get("journal") or "",
        "year": str(data.get("year") or ""),
        "doi": data.get("doi") or "",
        "pmid": data.get("pmid") or "",
        "arxiv_id": data.get("arxiv") or data.get("arxiv_id") or "",
        "url": data.get("url") or data.get("pdf_url") or "",
        "abstract": data.get("abstract") or "",
        "document_type": "article",
        "citation_count": data.get("citations") or 0,
    }


def to_bibtex(paper: dict) -> str:
    """Format paper as BibTeX entry."""
    p = normalize_paper(paper)
    key = generate_cite_key(paper)

    lines = [f"@article{{{key},"]

    title = clean_text(p["title"])
    if title:
        lines.append(f"  title = {{{title}}},")

    authors = p["authors_str"]
    lines.append(f"  author = {{{authors or 'Unknown'}}},")

    journal = clean_text(p["journal"])
    if journal:
        lines.append(f"  journal = {{{journal}}},")
    if p["year"]:
        lines.append(f"  year = {{{p['year']}}},")
    if p["doi"]:
        lines.append(f"  doi = {{{p['doi']}}},")
    if p["pmid"]:
        lines.append(f"  pmid = {{{p['pmid']}}},")
    if p["arxiv_id"]:
        lines.append(f"  eprint = {{{p['arxiv_id']}}},")
        lines.append("  archivePrefix = {arXiv},")
    if p["url"]:
        lines.append(f"  url = {{{p['url']}}},")

    # Remove trailing comma
    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]
    lines.append("}")

    return "\n".join(lines)


def to_ris(paper: dict) -> str:
    """Format paper as RIS entry."""
    p = normalize_paper(paper)
    lines = ["TY  - JOUR"]

    title = clean_text(p["title"])
    if title:
        lines.append(f"TI  - {title}")

    for author in p["authors_str"].split(" and "):
        author = author.strip()
        if author:
            lines.append(f"AU  - {author}")

    if p["journal"]:
        lines.append(f"JO  - {clean_text(p['journal'])}")
    if p["year"]:
        lines.append(f"PY  - {p['year']}")
    if p["doi"]:
        lines.append(f"DO  - {p['doi']}")
    if p["url"]:
        lines.append(f"UR  - {p['url']}")

    lines.append("ER  - ")
    return "\n".join(lines)


def to_text_citation(paper: dict, style: str = "apa") -> str:
    """Format paper as text citation in specified style."""
    p = normalize_paper(paper)
    authors = p["authors_str"] or "Unknown"
    year = p["year"] or "n.d."
    title = clean_text(p["title"])
    journal = clean_text(p["journal"])
    doi = p["doi"] or p["url"] or ""

    if style == "apa":
        return f"{authors} ({year}). {title}. {journal}. {doi}"
    elif style == "mla":
        return f'{authors}. "{title}." {journal}, {year}. {doi}.'
    elif style == "chicago":
        return f'{authors}. "{title}." {journal} ({year}). {doi}.'
    elif style == "vancouver":
        return f"{authors}. {title}. {journal}. {year}. Available from: {doi}"
    else:
        return f"{authors} ({year}). {title}. {journal}."


def format_papers(papers: list[dict], fmt: str) -> str:
    """Format list of papers to specified format."""
    if fmt == "json":
        return json.dumps(papers, indent=2, ensure_ascii=False)
    elif fmt == "bibtex":
        return "\n\n".join(to_bibtex(p) for p in papers)
    elif fmt == "ris":
        return "\n\n".join(to_ris(p) for p in papers)
    elif fmt in ["apa", "mla", "chicago", "vancouver"]:
        return "\n\n".join(to_text_citation(p, fmt) for p in papers)
    else:
        raise ValueError(f"Unknown format: {fmt}")


# ═══════════════════════════════════════════════════════════════════════
# Search Engine Classes
# ═══════════════════════════════════════════════════════════════════════


class ScholarSearch:
    """Multi-database academic literature search."""

    def __init__(self, email: str = "research@example.com", cache_dir: str = None):
        self.email = email
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": f"ScholarSearch/1.0 (mailto:{email})"})
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._cache_lock = threading.Lock()  # Thread-safe cache access

    def _cache_key(self, query: str, source: str, year_start: int, year_end: int, limit: int) -> str:
        """Generate a deterministic cache key for a search query."""
        import hashlib
        key_str = f"{query}|{source}|{year_start}|{year_end}|{limit}"
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]

    def _get_cached(self, key: str) -> list[dict[str, Any]] | None:
        """Retrieve cached results if available."""
        if not self.cache_dir:
            return None
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def _put_cached(self, key: str, results: list[dict[str, Any]]) -> None:
        """Store results in cache."""
        if not self.cache_dir:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self.cache_dir / f"{key}.json"
        try:
            cache_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass  # Cache write failure is non-fatal

    def _search_one_source(
        self, source: str, query: str, year_start: int, year_end: int, limit: int
    ) -> tuple[str, list[dict[str, any]], str | None]:
        """Search a single source. Returns (source, results, error)."""
        try:
            # Check cache first
            cache_key = self._cache_key(query, source, year_start, year_end, limit)
            with self._cache_lock:
                cached = self._get_cached(cache_key)
            if cached is not None:
                for r in cached:
                    r["_source"] = source
                    r["_cached"] = True
                return source, cached, None


            if source == "pubmed":
                results = self._search_pubmed(query, year_start, year_end, limit)
            elif source == "crossref":
                results = self._search_crossref(query, year_start, year_end, limit)
            elif source == "semanticscholar":
                results = self._search_semanticscholar(query, year_start, year_end, limit)
            elif source == "arxiv":
                results = self._search_arxiv(query, year_start, year_end, limit)
            elif source == "openalex":
                results = self._search_openalex(query, year_start, year_end, limit)
            elif source == "cnki":
                results = self._search_cnki(query, year_start, year_end, limit)
            elif source == "baidu_xueshu":
                results = self._search_baidu_xueshu(query, year_start, year_end, limit)
            else:
                return source, [], f"Unknown source '{source}'"

            for r in results:
                r["_source"] = source

            # Cache the results (thread-safe)
            with self._cache_lock:
                self._put_cached(cache_key, results)

            return source, results, None

        except Exception as e:
            return source, [], str(e)

    def search(
        self,
        query: str,
        sources: list[str] = None,
        year_start: int = None,
        year_end: int = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search multiple databases in parallel and aggregate results."""
        sources = sources or ["pubmed", "crossref", "semanticscholar", "arxiv", "openalex", "cnki", "baidu_xueshu"]
        all_results = []

        # Parallel search across sources (max 4 concurrent)
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self._search_one_source, source, query, year_start, year_end, limit): source
                for source in sources
            }
            for future in as_completed(futures):
                source, results, error = future.result()
                if error:
                    print(f"Error searching {source}: {error}", file=sys.stderr)
                else:
                    print(f"  {source}: {len(results)} results", file=sys.stderr)
                    all_results.extend(results)

        # Deduplicate by DOI (and by title for Chinese sources without DOI)
        seen_dois = set()
        seen_titles = set()
        unique_results = []
        for paper in all_results:
            doi = paper.get("doi")
            title = (paper.get("title") or "").strip().lower()
            if doi:
                if doi in seen_dois:
                    continue
                seen_dois.add(doi)
            elif title:
                # Fallback: dedup by normalized title for sources without DOI
                title_key = re.sub(r"\s+", "", title)
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)
            unique_results.append(paper)

        # Sort by citation count (descending), handle None values
        unique_results.sort(key=lambda x: x.get("citations") or 0, reverse=True)

        return unique_results[:limit * len(sources)]

    def _search_pubmed(
        self, query: str, year_start: int, year_end: int, limit: int
    ) -> list[dict[str, Any]]:
        """Search PubMed via E-utilities API."""
        # Build query
        pubmed_query = f"({query})[Title/Abstract]"
        if year_start and year_end:
            pubmed_query += f" AND {year_start}:{year_end}[pdat]"
        elif year_start:
            pubmed_query += f" AND {year_start}:{datetime.now().year}[pdat]"

        # Search for PMIDs
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        params = {
            "db": "pubmed",
            "term": pubmed_query,
            "retmode": "json",
            "retmax": min(limit, 100),
        }

        response = self.session.get(search_url, params=params, timeout=30)
        response.raise_for_status()
        pmids = response.json().get("esearchresult", {}).get("idlist", [])

        if not pmids:
            return []

        # Fetch metadata for all PMIDs in a single batch request
        results = []
        fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        ids = ",".join(pmids[:limit])

        params = {"db": "pubmed", "id": ids, "retmode": "json"}
        response = self.session.get(fetch_url, params=params, timeout=30)
        response.raise_for_status()
        result_map = response.json().get("result", {})

        for pmid in pmids[:limit]:
            result = result_map.get(pmid, {})
            if result and not result.get("error"):
                authors = [
                    a.get("name", "")
                    for a in result.get("authors", [])
                ]

                results.append({
                    "title": result.get("title", ""),
                    "authors": authors,
                    "year": result.get("pubdate", "")[:4] if result.get("pubdate") else None,
                    "journal": result.get("fulljournalname", ""),
                    "pmid": pmid,
                    "doi": result.get("elocationid", "").replace("doi: ", "") if "doi" in result.get("elocationid", "").lower() else None,
                    "abstract": None,  # Requires efetch
                    "citations": None,
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                })

        return results

    def _search_crossref(
        self, query: str, year_start: int, year_end: int, limit: int
    ) -> list[dict[str, Any]]:
        """Search CrossRef API."""
        url = "https://api.crossref.org/works"

        filter_parts = ["type:journal-article"]
        if year_start:
            filter_parts.append(f"from-pub-date:{year_start}")
        if year_end:
            filter_parts.append(f"until-pub-date:{year_end}")

        params = {
            "query.bibliographic": query,
            "rows": min(limit, 1000),
            "filter": ",".join(filter_parts),
            "mailto": self.email,
        }

        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()

        items = response.json().get("message", {}).get("items", [])
        results = []

        for item in items:
            authors = []
            for author in item.get("author", []):
                if "given" in author and "family" in author:
                    authors.append(f"{author['given']} {author['family']}")

            year = None
            if "published-print" in item:
                date_parts = item["published-print"].get("date-parts", [[]])[0]
                if date_parts:
                    year = date_parts[0]
            elif "published-online" in item:
                date_parts = item["published-online"].get("date-parts", [[]])[0]
                if date_parts:
                    year = date_parts[0]

            results.append({
                "title": item.get("title", [""])[0] if item.get("title") else "",
                "authors": authors,
                "year": year,
                "journal": item.get("container-title", [""])[0] if item.get("container-title") else "",
                "doi": item.get("DOI"),
                "abstract": item.get("abstract"),
                "citations": item.get("is-referenced-by-count", 0),
                "url": f"https://doi.org/{item['DOI']}" if item.get("DOI") else None,
            })

        return results

    def _search_semanticscholar(
        self, query: str, year_start: int, year_end: int, limit: int
    ) -> list[dict[str, Any]]:
        """Search Semantic Scholar API."""
        url = "https://api.semanticscholar.org/graph/v1/paper/search"

        params = {
            "query": query,
            "limit": min(limit, 100),
            "fields": "paperId,title,authors,year,abstract,citationCount,openAccessPdf,externalIds,venue",
        }

        if year_start and year_end:
            params["year"] = f"{year_start}-{year_end}"
        elif year_start:
            params["year"] = f"{year_start}-"
        elif year_end:
            params["year"] = f"-{year_end}"

        response = self.session.get(url, params=params, timeout=30)
        response.raise_for_status()

        papers = response.json().get("data", [])
        results = []

        for paper in papers:
            authors = [a.get("name", "") for a in paper.get("authors", [])]
            external_ids = paper.get("externalIds", {})
            oa_pdf = paper.get("openAccessPdf", {})

            results.append({
                "title": paper.get("title", ""),
                "authors": authors,
                "year": paper.get("year"),
                "journal": paper.get("venue", ""),
                "doi": external_ids.get("DOI"),
                "pmid": external_ids.get("PubMed"),
                "arxiv": external_ids.get("ArXiv"),
                "abstract": paper.get("abstract"),
                "citations": paper.get("citationCount", 0),
                "pdf_url": oa_pdf.get("url") if oa_pdf else None,
                "url": f"https://www.semanticscholar.org/paper/{paper.get('paperId')}" if paper.get("paperId") else None,
            })

        return results

    def _search_arxiv(
        self, query: str, year_start: int, year_end: int, limit: int
    ) -> list[dict[str, Any]]:
        """Search arXiv API."""
        search_query = f"all:{query}"
        url = f"https://export.arxiv.org/api/query?search_query={quote(search_query)}&start=0&max_results={limit}"

        time.sleep(3)  # Rate limit: 1 request per 3 seconds

        response = self.session.get(url, timeout=30)
        response.raise_for_status()

        root = ET.fromstring(response.content)
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }

        entries = root.findall("atom:entry", ns)
        results = []

        for entry in entries:
            arxiv_id = entry.find("atom:id", ns).text.split("/abs/")[-1]

            title_elem = entry.find("atom:title", ns)
            title = title_elem.text.strip().replace("\n", " ") if title_elem is not None else ""

            authors = []
            for author_elem in entry.findall("atom:author", ns):
                name_elem = author_elem.find("atom:name", ns)
                if name_elem is not None:
                    authors.append(name_elem.text)

            summary_elem = entry.find("atom:summary", ns)
            abstract = summary_elem.text.strip().replace("\n", " ") if summary_elem is not None else ""

            published_elem = entry.find("atom:published", ns)
            year = int(published_elem.text[:4]) if published_elem is not None else None

            # Apply year filter
            if year_start and year and year < year_start:
                continue
            if year_end and year and year > year_end:
                continue

            doi_elem = entry.find("arxiv:doi", ns)
            doi = doi_elem.text if doi_elem is not None else None

            results.append({
                "title": title,
                "authors": authors,
                "year": year,
                "journal": "arXiv",
                "arxiv": arxiv_id,
                "doi": doi,
                "abstract": abstract,
                "citations": None,
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                "url": f"https://arxiv.org/abs/{arxiv_id}",
            })

        return results

    def _search_openalex(
        self, query: str, year_start: int = None, year_end: int = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search OpenAlex (free, no API key required)."""
        import urllib.parse
        import urllib.request

        params = {
            "search": query,
            "per_page": str(min(limit, 50)),
            "mailto": self.email,
        }
        filters = []
        if year_start:
            filters.append(f"from_publication_date:{year_start}-01-01")
        if year_end:
            filters.append(f"to_publication_date:{year_end}-12-31")
        if filters:
            params["filter"] = ",".join(filters)

        url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": f"scholar_search.py (mailto:{self.email})"})

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"OpenAlex API error: {e}", file=sys.stderr)
            return []

        results = []
        for work in data.get("results", []):
            # Reconstruct abstract from inverted index
            abstract = ""
            inv_idx = work.get("abstract_inverted_index")
            if inv_idx:
                try:
                    word_positions = []
                    for word, positions in inv_idx.items():
                        for pos in positions:
                            word_positions.append((pos, word))
                    word_positions.sort()
                    abstract = " ".join(w for _, w in word_positions)
                except (TypeError, AttributeError):
                    pass

            # Extract authors
            authors = []
            for authorship in work.get("authorships", []):
                author = authorship.get("author", {})
                name = author.get("display_name", "")
                if name:
                    authors.append(name)

            # Extract DOI (OpenAlex stores as "https://doi.org/...")
            doi_url = work.get("doi", "")
            doi = doi_url.replace("https://doi.org/", "") if doi_url else None

            year = work.get("publication_year")

            journal = ""
            primary = work.get("primary_location") or {}
            source = primary.get("source") or {}
            journal = source.get("display_name", "")

            results.append({
                "title": work.get("title", ""),
                "authors": authors,
                "year": year,
                "journal": journal,
                "doi": doi,
                "abstract": abstract,
                "citations": work.get("cited_by_count"),
                "url": work.get("id", ""),
            })

        return results

    def _search_cnki(
        self, query: str, year_start: int = None, year_end: int = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search CNKI (China National Knowledge Infrastructure) via OpenSearch API."""
        import urllib.parse
        import urllib.request

        # CNKI OpenSearch endpoint (public, no auth required for basic search)
        base_url = "https://api.cnki.net/openapi/search"
        params = {
            "q": query,
            "pageSize": str(min(limit, 50)),
            "page": "1",
            "sort": "relevance",
        }
        if year_start:
            params["publishdate_from"] = f"{year_start}-01-01"
        if year_end:
            params["publishdate_to"] = f"{year_end}-12-31"

        url = base_url + "?" + urllib.parse.urlencode(params)
        headers = {
            "User-Agent": "scholar_search.py/1.0 (academic research tool)",
            "Accept": "application/json",
        }

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"CNKI API error: {e}", file=sys.stderr)
            # Fallback: try CNKI search page scraping
            return self._search_cnki_html(query, year_start, year_end, limit)

        results = []
        for item in data.get("data", data.get("results", [])):
            authors_raw = item.get("authors", item.get("author", ""))
            if isinstance(authors_raw, str):
                authors = [a.strip() for a in re.split(r"[;；,，]", authors_raw) if a.strip()]
            elif isinstance(authors_raw, list):
                authors = [str(a) for a in authors_raw]
            else:
                authors = []

            doi = item.get("doi", "")
            if not doi:
                # CNKI articles often don't have DOI; use CNKI URL as identifier
                doi = ""

            results.append({
                "title": item.get("title", ""),
                "authors": authors,
                "year": item.get("year") or item.get("publishyear"),
                "journal": item.get("journal", item.get("source", "")),
                "doi": doi,
                "abstract": item.get("abstract", item.get("summary", "")),
                "citations": item.get("citedcount", item.get("citations", 0)),
                "url": item.get("url", "https://kns.cnki.net/"),
                "source_db": "cnki",
                "language": "zh",
            })

        return results

    def _search_cnki_html(
        self, query: str, year_start: int = None, year_end: int = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Fallback: search CNKI via HTML scraping (when API unavailable)."""
        import urllib.parse
        import urllib.request

        # CNKI search URL
        search_url = "https://kns.cnki.net/kns8s/search"
        params = {
            "classid": "YSTT4HG0",
            "kw": query,
            "korder": "SU",
        }
        if year_start:
            params["txt_1_special1"] = f"{year_start}-{year_end or datetime.now().year}"

        url = search_url + "?" + urllib.parse.urlencode(params)
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html",
        }

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"CNKI HTML search error: {e}", file=sys.stderr)
            return []

        # Parse basic results from HTML
        results = []
        # Extract title-author pairs from search results
        title_pattern = re.compile(r'<a[^>]*class="fz14"[^>]*>(.*?)</a>', re.DOTALL)
        author_pattern = re.compile(r'<p class="author">.*?<a[^>]*>(.*?)</a>', re.DOTALL)

        titles = title_pattern.findall(html)
        authors_raw = author_pattern.findall(html)

        for i, title in enumerate(titles[:limit]):
            title = re.sub(r"<[^>]+>", "", title).strip()
            if not title:
                continue
            author_str = authors_raw[i] if i < len(authors_raw) else ""
            author_str = re.sub(r"<[^>]+>", "", author_str).strip()
            authors = [a.strip() for a in re.split(r"[;；,，]", author_str) if a.strip()]

            results.append({
                "title": title,
                "authors": authors,
                "year": None,
                "journal": "",
                "doi": "",
                "abstract": "",
                "citations": None,
                "url": "https://kns.cnki.net/",
                "source_db": "cnki",
                "language": "zh",
            })

        return results

    def _search_baidu_xueshu(
        self, query: str, year_start: int = None, year_end: int = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search Baidu Scholar (百度学术) for Chinese academic literature."""
        import urllib.parse
        import urllib.request

        params = {
            "wd": query,
            "pn": "0",
            "tn": "SE_baiduxueshu_c1gjeupa",
            "ie": "utf-8",
            "sc_as_para": "sc_lib:CNKI",
        }
        if year_start and year_end:
            params["sc_from"] = str(year_start)
            params["sc_to"] = str(year_end)

        url = "https://xueshu.baidu.com/s?" + urllib.parse.urlencode(params)
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html",
        }

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"Baidu Scholar error: {e}", file=sys.stderr)
            return []

        results = []
        # Parse Baidu Scholar results
        # Each result is in a div with class "sc_default_result"
        item_pattern = re.compile(
            r'<div class="sc_content"[^>]*>.*?<h3[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>'
            r'.*?</h3>(.*?)</div>\s*</div>',
            re.DOTALL
        )

        for match in item_pattern.finditer(html):
            url_path, title_html, meta_html = match.groups()
            title = re.sub(r"<[^>]+>", "", title_html).strip()
            if not title:
                continue

            # Extract authors from meta
            author_match = re.search(r'<p class="sc_info".*?>(.*?)</p>', meta_html, re.DOTALL)
            authors = []
            if author_match:
                author_text = re.sub(r"<[^>]+>", "", author_match.group(1)).strip()
                authors = [a.strip() for a in re.split(r"[;；,，]", author_text) if a.strip()]

            # Extract journal and year from meta
            journal_match = re.search(r'<a[^>]*class="sc_info_journal"[^>]*>(.*?)</a>', meta_html)
            journal = re.sub(r"<[^>]+>", "", journal_match.group(1)).strip() if journal_match else ""
            year_match = re.search(r'(\d{4})', meta_html)
            year = int(year_match.group(1)) if year_match else None

            # Extract citation count
            cite_match = re.search(r'被引用.*?(\d+)', meta_html)
            citations = int(cite_match.group(1)) if cite_match else 0

            results.append({
                "title": title,
                "authors": authors,
                "year": year,
                "journal": journal,
                "doi": "",
                "abstract": "",
                "citations": citations,
                "url": f"https://xueshu.baidu.com{url_path}" if url_path.startswith("/") else url_path,
                "source_db": "baidu_xueshu",
                "language": "zh" if re.search(r"[一-鿿]", title) else "en",
            })

        return results[:limit]


def main():
    parser = argparse.ArgumentParser(
        description="Search academic literature across multiple databases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search and show results
  python scholar_search.py "deep learning transformer"

  # Output as BibTeX for LaTeX
  python scholar_search.py "landslide detection" --format bibtex -o refs.bib

  # Output as APA citation style
  python scholar_search.py "neural network" --format apa --year 2022-2025

  # Filter by year and save JSON
  python scholar_search.py "machine learning" --year 2022-2025 -o results.json

Supported formats:
  json      - JSON format (default)
  bibtex    - BibTeX format for LaTeX
  ris       - RIS format for EndNote/Zotero
  apa       - APA citation style
  mla       - MLA citation style
  chicago   - Chicago citation style
  vancouver - Vancouver citation style
        """
    )

    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "--sources",
        default="crossref",
        help="Comma-separated list of sources: pubmed,crossref,semanticscholar,arxiv (default: crossref)"
    )
    parser.add_argument(
        "--year",
        help="Year range (e.g., 2022-2025 or 2023-)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum results (default: 20)"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "bibtex", "ris", "apa", "mla", "chicago", "vancouver"],
        default="json",
        help="Output format (default: json)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file (use '-' for stdout, default: stdout)"
    )
    parser.add_argument(
        "--email",
        default="research@example.com",
        help="Email for API polite pool"
    )
    parser.add_argument(
        "--cache-dir",
        help="Directory for caching search results (reduces API calls in batch runs)"
    )

    args = parser.parse_args()

    # Parse year range
    year_start, year_end = None, None
    if args.year:
        parts = args.year.split("-")
        if len(parts) == 2:
            year_start = int(parts[0]) if parts[0] else None
            year_end = int(parts[1]) if parts[1] else None
        else:
            year_start = int(args.year)

    # Parse sources
    sources = [s.strip().lower() for s in args.sources.split(",")]

    # Search
    print(f"Searching: {args.query}", file=sys.stderr)
    print(f"Sources: {', '.join(sources)}", file=sys.stderr)
    if year_start or year_end:
        print(f"Year: {year_start or ''}-{year_end or ''}", file=sys.stderr)

    searcher = ScholarSearch(email=args.email, cache_dir=args.cache_dir)
    results = searcher.search(
        query=args.query,
        sources=sources,
        year_start=year_start,
        year_end=year_end,
        limit=args.limit,
    )

    print(f"Found {len(results)} papers", file=sys.stderr)

    # Format output
    try:
        output = format_papers(results, args.format)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Write output
    if args.output == "-" or args.output is None:
        print(output)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Saved to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
