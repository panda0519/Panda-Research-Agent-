mock_openalex = mock.Mock()
mock_openalex.return_value.__enter__.return_value.json.return_value = {
    "author": {
        "id": "openalex:author/1234567890",
        "name": {
            "family": "Your Name",
            "given": "Your First Name"
        }
    }
}