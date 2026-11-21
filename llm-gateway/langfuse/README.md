`upstream-docker-compose.yml` は [langfuse/langfuse](https://github.com/langfuse/langfuse) の v4.76.0 の
`docker-compose.yml` をそのまま置いたもの (MIT License)。手を入れるのは `override.yml` だけにし、
更新するときは新しい版の compose で置き換えてから `override.yml` のダイジェストを上げる。
