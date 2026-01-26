# trackio_ui
Simple UI for trackio dashboard, written in FastHTML. Main reason for creating this was bad performance of gradio frontend to trackio. 

<img src="images/image.png" width="700">


With this ui you can configure the max number of points for graphs to prevent slow communication and rendering.

## Installation
```sh
pip install "trackio_ui @ https://github.com/ssslakter/trackio_ui.git"
```

## Getting started
To run the local server of trackio-ui you can run the following command.
```sh
trackio-ui --project "trackio-project" --port 8080
```
 Note that project name should match your trackio project. It will look for the project `.db` file in the `~/.cache/huggingface/trackio`.