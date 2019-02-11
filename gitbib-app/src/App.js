import React, {Component, useState} from 'react';
import gitbib_data from './quantum.json';
import './App.css';


function AuthorList(props) {
  if (props.authors) {
    const listItems = props.authors.map((author) => <li>{author.family + ', ' + author.given}</li>);
    return <ul className="AuthorList">{listItems}</ul>;
  }
  return <ul/>
}

function Dates(props) {
  return <p className="card-text">
    {props.entry['published-online'] && props.entry['published-online'] + " (online)"}
    {props.entry['published-online'] && props.entry['published-print'] && " -- "}
    {props.entry['published-print'] && props.entry['published-print'] + " (print)"}
  </p>
}

function ContainerTitle(props) {
  return <em>{props.entry['container-title']['full']} ({props.entry['container-title']['short']})</em>
}

function EntryCard(props) {
  const entry = props.entry;
  return <div className="card">
    <div className="card-block">
      <h4 className="card-title">{props.entry['title']}</h4>
      <h6 className="card-subtitle text-muted"><strong>{props.entry['ident']}</strong></h6>
      <p className="card-text"><AuthorList authors={props.entry['author']}/></p>
      <Dates entry={props.entry}/>
      <p class="card-text">
        {entry['container-title'] && <ContainerTitle entry={entry}/>}
        {entry['volume'] && entry['volume'] + ', '}
        {entry['issue'] && entry['issue'] + ', '}
        {entry['page'] && entry['page'] + '. '}
      </p>
    </div>
  </div>
}

// Take a json dictionary (which gets loaded as an Object) and turn it into a
// straight-up Array with the "keys" added to the field named ident.
var gitbib_data_entries_map = new Map(Object.entries(gitbib_data.entries));
gitbib_data_entries_map.forEach((value, key) => value.ident = key);
const gitbib_data_entries = Array.from(gitbib_data_entries_map.values());

function sortofMatches(text1, text2) {
  text1 = text1.toLowerCase();
  text2 = text2.toLowerCase();
  return text2.includes(text1);
}

function Entries() {
  const [searchText, setSearchText] = useState("");
  const [entries, setEntries] = useState(gitbib_data_entries);
  const entry_cards = entries.map((entry) => <EntryCard entry={entry}/>);

  return <div>
    <input type="text" placeholder="Filter" value={searchText} onChange={
      function (event) {
        let newval = event.target.value;
        setSearchText(newval);
        setEntries(gitbib_data_entries.filter(
            entry => entry['title'] && sortofMatches(newval, entry['title'])))
      }}/>
    {entry_cards}
  </div>;
}


class App extends Component {
  render() {
    return (
        <div className="App">
          <div className="container">
            <div className="row" style={{marginTop: '1rem'}}>
              <div className="col-xs-12 col-lg-9">
                <h5><a className="text-muted" href="user_info['index_url']">
                  <i className="fa fa-home" aria-hidden="true"/>
                  user_info slugname
                </a> |
                  All tags:
                </h5>

                <Entries/>
                <hr style={{margin: '2rem'}}/>
              </div>
            </div>
          </div>
        </div>
    );
  }
}

export default App;
