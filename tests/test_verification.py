from unittest import mock
mock_crossref = mock.Mock()
mock_crossref.return_value.__enter__.return_value.json.return_value = {
    "DOI": "10.1000/your_doi_here",
    "title": [
        "Your Title Here"
    ],
    "author": [
        {
            "family": "Your Name",
            "given": "Your First Name"
        }
    ],
    "published": {
        "date-parts": [[
            2022,
            1,
            1
        ]]
    }
}