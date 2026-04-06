from gerrit import GerritRestConnection
import pprint
if __name__ == "__main__":
    client = GerritRestConnection("http://localhost:8080/g", ("torii", "19D9aIn7zePb"))
    data , needed = client.query("3")
    # print(f"data for change is  {data}")
    pprint.pp(data , indent=2)

    depennds_on , needed_by = client._prepareDependencyListFromHttp(needed,"5b09d9c3ac6784572d6ef38397e46411e316c3d3",3)
    print(f"change 4 depends on {depennds_on} and is needed by {needed_by}")
    # changes 