from gerrit import GerritRestConnection

if __name__ == "__main__":
    client = GerritRestConnection("http://localhost:8080/g", ("torii", "19D9aIn7zePb"))
    print(client.query("1"))
